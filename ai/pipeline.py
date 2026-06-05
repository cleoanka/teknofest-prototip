"""
Uçtan uca çıkarım hattı.

Bir kareyi alır, aktif profile (normal/kritik) göre tüm blokları koşturur ve
hem FrameResult (mobil/dashboard çıktısı) hem de QoD tetik motoruna girilecek
TriggerContext üretir.

Blok A: araç + araç içi nesne tespiti (detector)
Blok B: takip (track_id, bbox büyüme)
Blok C: hız tahmini (speed)
Blok D: plaka OCR (yalnız kritik) (plate_ocr)
Blok E: sürücü durumu (driver_state)
Blok F: risk skoru (risk)
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np

from ai.schema import FrameResult, Vehicle, Detection, BBox
from ai.detector import build_detector, BaseDetector
from ai.tracking import IOUTracker
from ai.plate_ocr import PlateReader
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


class Pipeline:
    def __init__(self, detector: Optional[BaseDetector] = None, settings=None):
        self.s = settings or get_settings()
        self.detector = detector or build_detector(self.s)
        self.tracker = IOUTracker()
        self.plate_reader = PlateReader(mode=self.s.ai_mode)
        self.driver = DriverMonitor(mode=self.s.ai_mode)
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

        # Blok A — tespit
        detections = self.detector.detect(frame, conf=conf, profile=profile)

        # Blok B — takip (yalnız araçlar)
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
            # renk
            if frame is not None and frame.size:
                x1, y1, x2, y2 = [int(max(0, v)) for v in (pv.bbox.x1, pv.bbox.y1, pv.bbox.x2, pv.bbox.y2)]
                vehicle.color = _dominant_color(frame[y1:y2, x1:x2])
            # Blok C — hız
            vehicle.speed_kmh = estimate_speed(primary_track, w, h, fps, dt)

            # Blok D — plaka (yalnız kritik profil)
            if critical and frame is not None and frame.size:
                px1 = int(pv.bbox.x1 + 0.20 * (pv.bbox.x2 - pv.bbox.x1))
                px2 = int(pv.bbox.x2 - 0.20 * (pv.bbox.x2 - pv.bbox.x1))
                py1 = int(pv.bbox.y1 + 0.60 * (pv.bbox.y2 - pv.bbox.y1))
                py2 = int(pv.bbox.y2)
                crop = frame[max(0, py1):py2, max(0, px1):px2]
                vehicle.plate = self.plate_reader.read(crop if crop.size else None)

        result.vehicle = vehicle

        # Blok E — sürücü durumu
        result.driver = self.driver.assess(frame, detections, profile)

        # Blok F — risk
        result.risk = assess_risk(result.driver, vehicle.speed_kmh)

        # Süre / fps
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
