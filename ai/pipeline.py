"""
Uçtan uca çıkarım hattı.

Blok A: Araç + araç içi nesne tespiti (YOLOv8)
Blok B: Takip (track_id, bbox büyüme, swerving)
Blok C: Hız tahmini
Blok D: İki aşamalı plaka tespiti
           Aşama 1 → araç crop al (padding %5)
           Aşama 2 → LP dedektör SADECE araç crop üzerinde çalışır
           → false positive (trafik levhası, duvar) tamamen önlenir
           → koordinat dönüşümü ile full-frame bbox hesaplanır
           → plate_pixel_width → mesafe kalibrasyonu (52cm / px_w)
Blok E: Sürücü durumu (MediaPipe + sürücü/yolcu ROI ayrımı)
Blok F: Risk skoru
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np

from ai.schema import FrameResult, Vehicle, Detection, BBox, PlateResult
from ai.detector import build_detector, BaseDetector
from ai.tracking import IOUTracker
from ai.plate_ocr import PlateReader
from ai.lp_detector import get_lp_detector
from ai.plate_crop import looks_like_plate, refine_to_frame, plate_sharpness
from ai.plate_tracker import PlateTracker
from ai.driver_state import DriverMonitor
from ai.speed import estimate_speed
from ai.calibration import MetricSpeedEstimator
from ai.risk import assess_risk
from ai.qod_trigger import TriggerContext
from config.settings import get_settings


def _dominant_color(crop: np.ndarray) -> Optional[str]:
    if crop is None or crop.size == 0:
        return None
    b, g, r = [float(crop[..., i].mean()) for i in range(3)] if crop.ndim == 3 else (0, 0, 0)
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx > 200 and mn > 180:
        return "beyaz"
    if mx < 70:
        return "siyah"
    if r >= g and r >= b:
        return "kirmizi"
    if g >= r and g >= b:
        return "yesil"
    return "mavi"


def _vehicle_crop(
    frame: np.ndarray,
    vehicle_bbox: BBox,
    padding: float = 0.05,
) -> Tuple[Optional[np.ndarray], Tuple[int, int]]:
    """
    Araç bbox'ından %5 padding'li crop alır.
    Dönüş: (crop, (x_offset, y_offset)) — lokal koordinatları full-frame'e çevirmek için.
    """
    fh, fw = frame.shape[:2]
    vw = vehicle_bbox.x2 - vehicle_bbox.x1
    vh = vehicle_bbox.y2 - vehicle_bbox.y1
    x1 = max(0, int(vehicle_bbox.x1 - padding * vw))
    y1 = max(0, int(vehicle_bbox.y1 - padding * vh))
    x2 = min(fw, int(vehicle_bbox.x2 + padding * vw))
    y2 = min(fh, int(vehicle_bbox.y2 + padding * vh))
    crop = frame[y1:y2, x1:x2]
    return (crop if crop.size > 0 else None), (x1, y1)


class Pipeline:
    def __init__(self, detector: Optional[BaseDetector] = None, settings=None):
        self.s = settings or get_settings()
        self.detector = detector or build_detector(self.s)
        self.tracker = IOUTracker()
        self.plate_reader = PlateReader(mode=self.s.ai_mode)
        self.driver = DriverMonitor(mode=self.s.ai_mode)
        self.lp_detector = get_lp_detector(mode=self.s.ai_mode)
        self.plate_tracker = PlateTracker(ttl_frames=self.s.plate_track_ttl_frames)
        self.speed_estimator = MetricSpeedEstimator(self.s)
        self._last_t = time.time()
        self._frame_id = 0

    @property
    def mode_name(self) -> str:
        return type(self.detector).__name__

    def _find_plate(
        self, frame: np.ndarray, vehicle_bbox: Optional[BBox], w: int, h: int
    ) -> Tuple[Optional[BBox], Optional[np.ndarray]]:
        """LP dedektörle plaka adayını bul.

        Araç bbox varsa SADECE araç crop'unda arar → araç dışı false positive
        (trafik levhası, duvar) tamamen elenir. Araç bbox yoksa (TOGG: COCO araç
        kutusu veremez) full frame'de arar.

        Dönüş: (full_frame_bbox | None, plate_crop | None). Crop, araç crop'undan
        alınır (piksel kalitesi daha iyi); bbox full-frame koordinata çevrilir.
        """
        if vehicle_bbox is not None:
            veh_crop, (ox, oy) = _vehicle_crop(frame, vehicle_bbox)
            if veh_crop is None or veh_crop.size == 0:
                return None, None
            local = self.lp_detector.detect(veh_crop)
            if not local:
                return None, None
            best = max(local, key=lambda b: b.area)
            bbox = BBox(x1=best.x1 + ox, y1=best.y1 + oy,
                        x2=best.x2 + ox, y2=best.y2 + oy)
            lx1, ly1 = max(0, int(best.x1)), max(0, int(best.y1))
            lx2 = min(veh_crop.shape[1], int(best.x2))
            ly2 = min(veh_crop.shape[0], int(best.y2))
            crop = veh_crop[ly1:ly2, lx1:lx2]
            return bbox, (crop if crop.size > 0 else None)

        # TOGG / araç bbox yok → full frame
        full = self.lp_detector.detect(frame)
        if not full:
            return None, None
        best = max(full, key=lambda b: b.area)
        fx1, fy1 = max(0, int(best.x1)), max(0, int(best.y1))
        fx2, fy2 = min(w, int(best.x2)), min(h, int(best.y2))
        crop = frame[fy1:fy2, fx1:fx2]
        return best, (crop if crop.size > 0 else None)

    def process(self, frame: np.ndarray, critical: bool,
                fps: float = 30.0,
                frame_ts: Optional[float] = None) -> Tuple[FrameResult, TriggerContext]:
        """frame_ts: bu karenin VİDEO ZAMAN ÇİZGİSİ damgası (s) — video PTS ya da
        canlı akışta istemci yakalama zamanı (client_ts). Verilirse track'lere
        yazılır ve metrik hız Δt'si bundan ölçülür (Aşama 0). Yoksa wall-clock'a
        düşülür (canlı akışta kareler gerçek zamanlı geldiği için makul yaklaşım).
        """
        t0 = time.time()
        dt = max(1e-3, t0 - self._last_t)   # işleme (perf) Δt'si — fps/latency raporu için
        self._last_t = t0
        # Hız için video-zaman çizgisi damgası: PTS/client_ts varsa onu, yoksa wall-clock'u kullan
        vts = frame_ts if (frame_ts is not None and frame_ts > 0) else t0
        self._frame_id += 1
        profile = "critical" if critical else "normal"
        conf = self.s.conf_critical if critical else self.s.conf_normal
        h, w = (frame.shape[:2] if frame is not None and frame.size else (0, 0))

        # Blok A — araç + nesne tespiti
        detections = self.detector.detect(frame, conf=conf, profile=profile)

        # Blok B — araç takibi
        veh_dets = [d for d in detections if d.label == "vehicle"]
        veh_boxes = [(d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2) for d in veh_dets]
        track_ids = self.tracker.update(veh_boxes, ts=vts)
        for d, tid in zip(veh_dets, track_ids):
            d.track_id = tid

        result = FrameResult(
            frame_id=self._frame_id,
            ts=t0,
            mode="CRITICAL" if critical else "NORMAL",
            model_profile=(self.s.yolo_model_critical if critical else self.s.yolo_model_normal).replace(".pt", ""),
            detections=detections,
        )

        vehicle = Vehicle()
        primary_track = None

        if veh_dets:
            idx = max(range(len(veh_dets)), key=lambda i: veh_dets[i].bbox.area)
            pv = veh_dets[idx]
            primary_track = self.tracker.get(pv.track_id)
            vehicle.present = True
            vehicle.track_id = pv.track_id
            vehicle.vtype = pv.attributes.get("vtype")
            vehicle.bbox = pv.bbox

            if frame is not None and frame.size:
                x1i, y1i = int(max(0, pv.bbox.x1)), int(max(0, pv.bbox.y1))
                x2i, y2i = int(max(0, pv.bbox.x2)), int(max(0, pv.bbox.y2))
                vehicle.color = _dominant_color(frame[y1i:y2i, x1i:x2i])

            # Blok C — hız. Önce metrik (oto-kalibrasyon ısındıysa); yoksa eski
            # kalibrasyonsuz sezgisel (is_calibrated=False). Ölçek-alanı önceki
            # karelerin plaka/araç ölçümlerinden kurulur (warm-up, §4.3).
            metric_kmh, calibrated = self.speed_estimator.estimate(primary_track)
            if calibrated:
                vehicle.speed_kmh = metric_kmh
                vehicle.speed_is_calibrated = True
            else:
                vehicle.speed_kmh = estimate_speed(primary_track, w, h, fps, dt)
                vehicle.speed_is_calibrated = False

            # Swerving
            if primary_track:
                vehicle.swerving = primary_track.is_swerving()

            # Sürücü / yolcu ROI
            vehicle.driver_bbox = DriverMonitor.driver_roi(vehicle.bbox, (h, w))
            vehicle.passenger_bbox = DriverMonitor.passenger_roi(vehicle.bbox, (h, w))

        # Blok D — Plaka tespiti + crop + araç-id'sine bağlı kararlılık (kritik profilde)
        if critical and frame is not None and frame.size:
            # Aşama 1+2: plaka adayını bul (araç crop tercih; yoksa full frame → TOGG).
            cand_bbox, plate_crop = self._find_plate(frame, vehicle.bbox, w, h)

            cur_plate = PlateResult()
            cur_bbox: Optional[BBox] = None
            cur_sharp = 0.0

            # Saçma bölgeleri ele: yalnız plaka-benzeri crop OCR'a gönderilir
            # (trafik levhası, far, tampon yazısı vb. burada düşer).
            if plate_crop is not None and looks_like_plate(
                plate_crop,
                min_std=self.s.plate_min_likeness_std,
                min_edge_density=self.s.plate_min_edge_density,
            ):
                # "Siyah çerçeveyi takip et": ROI'yi plakanın koyu çerçevesine sıkılaştır.
                ocr_crop = plate_crop
                if self.s.plate_refine_crop:
                    refined = refine_to_frame(plate_crop, deskew=self.s.plate_deskew)
                    if refined is not None and refined.size > 0:
                        ocr_crop = refined
                cur_sharp = plate_sharpness(ocr_crop)
                cur_plate = self.plate_reader.read(ocr_crop)
                cur_bbox = cand_bbox

            # Araç id'sine bağlı süreklilik: en iyi okumayı sakla, kararlıyı geri al.
            # Plaka bu karede yoksa aracın son bilinen plakası korunur (titremez,
            # boş/yanlış kayda düşmez).
            if vehicle.track_id is not None:
                self.plate_tracker.update(
                    vehicle.track_id, cur_plate, cur_bbox, cur_sharp, self._frame_id)
                stable_plate, stable_bbox, stable_pw = \
                    self.plate_tracker.resolve(vehicle.track_id)
                vehicle.plate = stable_plate if stable_plate.text else cur_plate
                if stable_bbox is not None:
                    vehicle.plate_bbox = stable_bbox
                    vehicle.plate_pixel_width = stable_pw
                elif cur_bbox is not None:
                    vehicle.plate_bbox = cur_bbox
                    vehicle.plate_pixel_width = round(cur_bbox.width, 1)
            else:
                # track_id yok (ör. TOGG full-frame, araç bbox üretilemedi) → anlık sonuç.
                vehicle.plate = cur_plate
                if cur_bbox is not None:
                    vehicle.plate_bbox = cur_bbox
                    vehicle.plate_pixel_width = round(cur_bbox.width, 1)

            # TOGG: araç yoksa ama plaka bulunduysa present=True
            if not vehicle.present and vehicle.plate_bbox is not None:
                vehicle.present = True
                vehicle.vtype = "vehicle"

        # Oto-kalibrasyon ölçek-alanı birikimi (§4.3 ısınma) — sonraki karelerin
        # metrik hızı için. Plaka: yüksek-kesinlik çapa; tüm araçlar: sınıf-bazlı
        # genişlikten düşük-ağırlıklı yedek (Aşama 2). Hız (Blok C) önceki karelerin
        # ölçeğini kullandığından sıralama güvenli.
        if vehicle.plate_bbox is not None:
            self.speed_estimator.observe_plate(vehicle.plate_bbox)
        for d in veh_dets:
            self.speed_estimator.observe_vehicle(d.bbox, d.attributes.get("vtype"))
        if vehicle.present:
            self.speed_estimator.maybe_fit()
        # Silinen track'lerin hız-EMA durumunu temizle (bellek sızıntısı önleme)
        alive_ids = set(self.tracker.tracks.keys())
        self.speed_estimator.prune(alive_ids)
        # Sahneden çıkmış araçların plaka durumunu da temizle (ttl ile)
        self.plate_tracker.prune(alive_ids, self._frame_id)

        # Aşama 4 — opsiyonel otomatik şerit homografisi (varsayılan kapalı).
        # Açıksa periyodik olarak kareden şerit→homografi dener; kurulursa metrik
        # hız ppm(y) yerine perspektif-tam homografiyi kullanır (§7.1).
        if (getattr(self.s, "homography_auto", False)
                and self.speed_estimator.homography is None
                and frame is not None and frame.size
                and self._frame_id % max(1, self.s.homography_calib_interval) == 0):
            from ai.lane_detect import detect_lane_homography
            H = detect_lane_homography(frame, self.s.lane_width_m, self.s.dash_pitch_m)
            if H is not None:
                self.speed_estimator.set_homography(H)

        result.vehicle = vehicle

        # Blok E — sürücü durumu
        result.driver = self.driver.assess(
            frame, detections, profile, vehicle_bbox=vehicle.bbox
        )

        # Blok F — risk skoru
        result.risk = assess_risk(result.driver, vehicle.speed_kmh, vehicle.swerving)

        result.latency_ms = round((time.time() - t0) * 1000, 1)
        result.fps = round(1.0 / dt, 1)

        ctx = TriggerContext(
            bbox_growth=primary_track.area_growth_ratio() if primary_track else 0.0,
            vehicle_present=vehicle.present,
            vehicle_conf=max([d.confidence for d in veh_dets], default=0.0),
            vehicle_norm_y2=(vehicle.bbox.y2 / h) if (vehicle.bbox and h) else 0.0,
            plate_roi_present=bool(critical and vehicle.present),
            plate_ocr_conf=vehicle.plate.confidence,
            ambiguous_object_confs=[d.confidence for d in detections
                                    if d.label in ("phone", "cigarette")],
        )
        return result, ctx
