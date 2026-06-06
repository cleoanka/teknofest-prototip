"""
Uçtan uca çıkarım hattı.

Blok A: Araç + araç içi nesne tespiti (YOLOv8)
Blok B: Takip (track_id, bbox büyüme, swerving)
Blok C: Hız tahmini
Blok D: Plaka tespiti (LP dedektör → OCR)  — araçtan bağımsız çalışır
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


def _nearest_plate_to_vehicle(vehicle_bbox: BBox, plate_bboxes) -> Optional[BBox]:
    """Birden fazla plaka varsa araç merkezine en yakın plakayı seç."""
    if not plate_bboxes:
        return None
    vcx, vcy = vehicle_bbox.cx, vehicle_bbox.cy
    best, best_dist = None, float("inf")
    for pb in plate_bboxes:
        dx = pb.cx - vcx
        dy = pb.cy - vcy
        d = (dx * dx + dy * dy) ** 0.5
        if d < best_dist:
            best, best_dist = pb, d
    # Plakanın araç bbox'ının içinde veya yakınında olmasını kontrol et
    margin = max(vehicle_bbox.area ** 0.5 * 0.5, 50)
    if best_dist > margin and best is not None:
        # Araçtan çok uzaksa plakayla eşleştirme (başka araca ait olabilir)
        in_veh = (best.x1 >= vehicle_bbox.x1 - margin and best.x2 <= vehicle_bbox.x2 + margin)
        if not in_veh:
            return None
    return best


def _fallback_plate_crop(frame: np.ndarray, vehicle_bbox: BBox) -> Optional[np.ndarray]:
    """LP dedektör plaka bulamazsa araç bbox alt bölgesini kırp."""
    if frame is None or frame.size == 0:
        return None
    v = vehicle_bbox
    w = v.x2 - v.x1
    h = v.y2 - v.y1
    px1 = int(v.x1 + 0.05 * w)
    px2 = int(v.x2 - 0.05 * w)
    py1 = int(v.y1 + 0.50 * h)
    py2 = int(v.y2 - 0.01 * h)
    crop = frame[max(0, py1):py2, max(0, px1):px2]
    return crop if crop.size > 0 else None


class Pipeline:
    def __init__(self, detector: Optional[BaseDetector] = None, settings=None):
        self.s = settings or get_settings()
        self.detector = detector or build_detector(self.s)
        self.tracker = IOUTracker()
        self.plate_reader = PlateReader(mode=self.s.ai_mode)
        self.driver = DriverMonitor(mode=self.s.ai_mode, settings=self.s)
        self.lp_detector = get_lp_detector()
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
                x1, y1, x2, y2 = [int(max(0, v)) for v in (pv.bbox.x1, pv.bbox.y1, pv.bbox.x2, pv.bbox.y2)]
                vehicle.color = _dominant_color(frame[y1:y2, x1:x2])

            # Blok C — hız
            vehicle.speed_kmh = estimate_speed(primary_track, w, h, fps, dt)

            # Swerving (zigzag tespiti)
            if primary_track:
                vehicle.swerving = primary_track.is_swerving()

            # Sürücü / yolcu ROI
            vehicle.driver_bbox = DriverMonitor.driver_roi(vehicle.bbox, (h, w))
            vehicle.passenger_bbox = DriverMonitor.passenger_roi(vehicle.bbox, (h, w))

        # Blok D — plaka tespiti (LP dedektörden bağımsız, kritik profilde)
        if critical and frame is not None and frame.size:
            # LP dedektör tam çerçevede çalışır (araç yoksa bile plaka bulunabilir)
            plate_bboxes = self.lp_detector.detect(frame, conf=0.20)

            plate_crop = None
            selected_plate_bbox = None

            if plate_bboxes:
                if vehicle.bbox:
                    selected_plate_bbox = _nearest_plate_to_vehicle(vehicle.bbox, plate_bboxes)
                    if selected_plate_bbox is None:
                        # TOGG gibi durum: COCO yanlış araç bbox'ı veriyor,
                        # LP dedektör gerçek plaka konumunu buluyor → plakayı yine de kullan
                        selected_plate_bbox = max(plate_bboxes, key=lambda b: b.area)
                else:
                    # Araç yoksa en büyük plakayı al
                    selected_plate_bbox = max(plate_bboxes, key=lambda b: b.area)

                if selected_plate_bbox:
                    x1 = max(0, int(selected_plate_bbox.x1))
                    y1 = max(0, int(selected_plate_bbox.y1))
                    x2 = min(w, int(selected_plate_bbox.x2))
                    y2 = min(h, int(selected_plate_bbox.y2))
                    plate_crop = frame[y1:y2, x1:x2]
                    if plate_crop.size == 0:
                        plate_crop = None

            # LP dedektör plaka bulamazsa araç bbox alt bölgesini fallback
            if plate_crop is None and vehicle.bbox:
                plate_crop = _fallback_plate_crop(frame, vehicle.bbox)

            if plate_crop is not None:
                vehicle.plate = self.plate_reader.read(plate_crop)
                if selected_plate_bbox:
                    vehicle.plate_bbox = selected_plate_bbox

            # LP dedektörden plaka bulundu ama araç yoksa vehicle.present=True yap
            if not vehicle.present and plate_bboxes:
                vehicle.present = True
                vehicle.vtype = "vehicle"
                vehicle.plate_bbox = selected_plate_bbox

        result.vehicle = vehicle

        # Blok E — sürücü durumu (sürücü/yolcu ROI ayrımı)
        result.driver = self.driver.assess(
            frame, detections, profile, vehicle_bbox=vehicle.bbox
        )

        # Swerving risk faktörü olarak eklenir
        if vehicle.swerving and "swerving" not in [f for f in result.driver.__dict__]:
            pass  # risk.py içinde vehicle.swerving kontrol edilir

        # Blok F — risk skoru
        result.risk = assess_risk(result.driver, vehicle.speed_kmh, vehicle.swerving)

        result.latency_ms = round((time.time() - t0) * 1000, 1)
        result.fps = round(1.0 / dt, 1)

        # QoD tetik bağlamı
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
