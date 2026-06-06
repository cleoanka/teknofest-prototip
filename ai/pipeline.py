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

from ai.schema import FrameResult, Vehicle, Detection, BBox
from ai.detector import build_detector, BaseDetector
from ai.tracking import IOUTracker
from ai.plate_ocr import PlateReader
from ai.lp_detector import get_lp_detector
from ai.driver_state import DriverMonitor
from ai.speed import estimate_speed
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


def _fallback_plate_crop(frame: np.ndarray, vehicle_bbox: BBox) -> Optional[np.ndarray]:
    """LP dedektör başarısız olursa araç bbox alt %50'sini OCR'a gönderir."""
    if frame is None or frame.size == 0:
        return None
    v = vehicle_bbox
    vw = v.x2 - v.x1
    vh = v.y2 - v.y1
    px1 = int(v.x1 + 0.05 * vw)
    px2 = int(v.x2 - 0.05 * vw)
    py1 = int(v.y1 + 0.50 * vh)
    py2 = int(v.y2 - 0.01 * vh)
    crop = frame[max(0, py1):py2, max(0, px1):px2]
    return crop if crop.size > 0 else None


class Pipeline:
    def __init__(self, detector: Optional[BaseDetector] = None, settings=None):
        self.s = settings or get_settings()
        self.detector = detector or build_detector(self.s)
        self.tracker = IOUTracker()
        self.plate_reader = PlateReader(mode=self.s.ai_mode)
        self.driver = DriverMonitor(mode=self.s.ai_mode)
        self.lp_detector = get_lp_detector(mode=self.s.ai_mode)
        self._last_t = time.time()
        self._frame_id = 0

    @property
    def mode_name(self) -> str:
        return type(self.detector).__name__

    def process(self, frame: np.ndarray, critical: bool,
                fps: float = 30.0) -> Tuple[FrameResult, TriggerContext]:
        t0 = time.time()
        dt = max(1e-3, t0 - self._last_t)
        self._last_t = t0
        self._frame_id += 1
        profile = "critical" if critical else "normal"
        conf = self.s.conf_critical if critical else self.s.conf_normal
        h, w = (frame.shape[:2] if frame is not None and frame.size else (0, 0))

        # Blok A — araç + nesne tespiti
        detections = self.detector.detect(frame, conf=conf, profile=profile)

        # Blok B — araç takibi
        veh_dets = [d for d in detections if d.label == "vehicle"]
        veh_boxes = [(d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2) for d in veh_dets]
        track_ids = self.tracker.update(veh_boxes)
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

            # Blok C — hız
            vehicle.speed_kmh = estimate_speed(primary_track, w, h, fps, dt)

            # Swerving
            if primary_track:
                vehicle.swerving = primary_track.is_swerving()

            # Sürücü / yolcu ROI
            vehicle.driver_bbox = DriverMonitor.driver_roi(vehicle.bbox, (h, w))
            vehicle.passenger_bbox = DriverMonitor.passenger_roi(vehicle.bbox, (h, w))

        # Blok D — İki aşamalı plaka tespiti (kritik profilde)
        if critical and frame is not None and frame.size:
            selected_plate_bbox: Optional[BBox] = None
            plate_crop: Optional[np.ndarray] = None

            if vehicle.bbox:
                # Aşama 1: Araç crop (araç dışı false positive'leri eliyor)
                veh_crop, (ox, oy) = _vehicle_crop(frame, vehicle.bbox)

                if veh_crop is not None and veh_crop.size > 0:
                    # Aşama 2: LP dedektör SADECE araç crop üzerinde
                    local_bboxes = self.lp_detector.detect(veh_crop)

                    if local_bboxes:
                        best_local = max(local_bboxes, key=lambda b: b.area)

                        # Lokal koordinat → full-frame koordinat
                        selected_plate_bbox = BBox(
                            x1=best_local.x1 + ox, y1=best_local.y1 + oy,
                            x2=best_local.x2 + ox, y2=best_local.y2 + oy,
                        )
                        # Plate crop: araç crop üzerindeki piksel kalitesi daha iyi
                        lx1 = max(0, int(best_local.x1))
                        ly1 = max(0, int(best_local.y1))
                        lx2 = min(veh_crop.shape[1], int(best_local.x2))
                        ly2 = min(veh_crop.shape[0], int(best_local.y2))
                        plate_crop = veh_crop[ly1:ly2, lx1:lx2]
                        if plate_crop.size == 0:
                            plate_crop = None
            else:
                # TOGG senaryosu: COCO araç bbox veremiyor → full frame'de ara
                full_bboxes = self.lp_detector.detect(frame)
                if full_bboxes:
                    best_fb = max(full_bboxes, key=lambda b: b.area)
                    selected_plate_bbox = best_fb
                    fbx1 = max(0, int(best_fb.x1))
                    fby1 = max(0, int(best_fb.y1))
                    fbx2 = min(w, int(best_fb.x2))
                    fby2 = min(h, int(best_fb.y2))
                    plate_crop = frame[fby1:fby2, fbx1:fbx2]
                    if plate_crop is not None and plate_crop.size == 0:
                        plate_crop = None

            # Fallback: LP dedektör plaka bulamazsa araç alt bölgesi
            if plate_crop is None and vehicle.bbox:
                plate_crop = _fallback_plate_crop(frame, vehicle.bbox)

            if plate_crop is not None:
                vehicle.plate = self.plate_reader.read(plate_crop)

            if selected_plate_bbox is not None:
                vehicle.plate_bbox = selected_plate_bbox
                vehicle.plate_pixel_width = round(selected_plate_bbox.width, 1)

            # TOGG: araç yoksa ama plaka bulunduysa present=True
            if not vehicle.present and selected_plate_bbox:
                vehicle.present = True
                vehicle.vtype = "vehicle"

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
