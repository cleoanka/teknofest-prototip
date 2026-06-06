"""
Uçtan uca çıkarım hattı.

Blok A: araç + araç içi nesne tespiti (detector)
Blok B: takip (track_id, bbox büyüme)
Blok C: hız tahmini (speed)
Blok D: plaka OCR — akıllı Canny crop (plate_ocr)
Blok E: sürücü durumu (driver_state)
Blok F: risk skoru (risk)

Düzeltmeler (v2):
  - Kör %60 Y-crop → Canny kenar yoğunluğu ile sliding-window plaka tespiti
  - vehicle.plate None guard → AttributeError önlendi
  - Normal profilde büyük araçta da OCR çalışır (bbox_area_ratio > 0.15)
  - run_ocr değişkeni veh_dets dışında da güvenli erişilir
"""
from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np

from ai.schema import FrameResult, Vehicle, Detection, BBox
from ai.detector import build_detector, BaseDetector
from ai.tracking import IOUTracker
from ai.plate_ocr import PlateReader, PlateResult, MIN_PLATE_WIDTH, MIN_PLATE_HEIGHT
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


def _find_plate_crop(frame: np.ndarray, bbox: BBox) -> Optional[np.ndarray]:
    """
    Araç bbox'ından plaka bölgesini akıllıca çıkar.

    Algoritma:
    1. Araç bbox'ının alt %50'sini ara bölge olarak al (plaka asla üstte değil).
    2. Yatay %10 marj ekle (plaka genişliği ≈ araç genişliğinin %80'i).
    3. Canny kenar tespiti → her satırın yatay kenar yoğunluğu.
    4. Sliding window (plaka_yüksekliği ≈ bbox_yüksekliğinin %18'i) ile en yoğun
       satır grubunu bul.
    5. O satır grubunu crop olarak döndür.

    cv2 yoksa (mock ortam): alt %28–70 strip — eski koddan daha iyi fallback.
    """
    if frame is None or frame.size == 0:
        return None

    h_frame, w_frame = frame.shape[:2]
    x1 = max(0, int(bbox.x1))
    y1 = max(0, int(bbox.y1))
    x2 = min(w_frame, int(bbox.x2))
    y2 = min(h_frame, int(bbox.y2))

    bh = y2 - y1
    bw = x2 - x1
    if bh < 20 or bw < 20:
        return None

    # Yatay marj
    h_margin = max(1, int(bw * 0.10))
    px1 = max(0, x1 + h_margin)
    px2 = min(w_frame, x2 - h_margin)

    # Arama bölgesi: alt %50
    search_y1 = y1 + int(bh * 0.50)
    search_region = frame[search_y1:y2, px1:px2]

    if search_region.size == 0:
        return None

    try:
        import cv2

        gray = (cv2.cvtColor(search_region, cv2.COLOR_BGR2GRAY)
                if search_region.ndim == 3 else search_region.copy())

        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)

        row_scores = edges.sum(axis=1).astype(float)
        if row_scores.max() == 0:
            raise ValueError("no edges detected")

        # Plaka strip yüksekliği ≈ araç bbox yüksekliğinin %18'i, min 16px
        plate_strip_h = max(16, int(bh * 0.18))
        window = np.ones(plate_strip_h)
        windowed = np.convolve(row_scores, window, mode="same")
        best_row = int(np.argmax(windowed))

        half = plate_strip_h // 2
        abs_cy = search_y1 + best_row
        crop_y1 = max(0, abs_cy - half)
        crop_y2 = min(h_frame, abs_cy + half + (plate_strip_h % 2))
        crop = frame[crop_y1:crop_y2, px1:px2]

    except Exception:
        # Fallback: alt %28–70 strip
        strip_y1 = y1 + int(bh * 0.72)
        crop = frame[strip_y1:y2, px1:px2]

    if crop is None or crop.size == 0:
        return None

    ch, cw = crop.shape[:2]
    if cw < MIN_PLATE_WIDTH or ch < MIN_PLATE_HEIGHT:
        return None

    return crop


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
        run_ocr = False  # TriggerContext'te her zaman erişilebilir olsun

        if veh_dets:
            idx = max(range(len(veh_dets)), key=lambda i: veh_dets[i].bbox.area)
            pv = veh_dets[idx]
            primary_track = self.tracker.get(pv.track_id)
            vehicle.present = True
            vehicle.track_id = pv.track_id
            vehicle.vtype = pv.attributes.get("vtype")
            vehicle.bbox = pv.bbox

            # Renk
            if frame is not None and frame.size:
                x1i = int(max(0, pv.bbox.x1))
                y1i = int(max(0, pv.bbox.y1))
                x2i = int(max(0, pv.bbox.x2))
                y2i = int(max(0, pv.bbox.y2))
                vehicle.color = _dominant_color(frame[y1i:y2i, x1i:x2i])

            # Blok C — hız
            vehicle.speed_kmh = estimate_speed(primary_track, w, h, fps, dt)

            # Blok D — plaka OCR
            # Kritik modda her zaman; normal modda araç yeterince büyükse
            bbox_area_ratio = (pv.bbox.area / (w * h)) if (w and h) else 0.0
            run_ocr = critical or (bbox_area_ratio > 0.15)

            if run_ocr and frame is not None and frame.size:
                plate_crop = _find_plate_crop(frame, pv.bbox)
                vehicle.plate = self.plate_reader.read(plate_crop)

        result.vehicle = vehicle

        # Blok E — sürücü durumu
        result.driver = self.driver.assess(frame, detections, profile)

        # Blok F — risk
        result.risk = assess_risk(result.driver, vehicle.speed_kmh)

        # Süre / fps
        result.latency_ms = round((time.time() - t0) * 1000, 1)
        result.fps = round(1.0 / dt, 1)

        # vehicle.plate None guard — Vehicle schema'da Optional[PlateResult] olabilir
        plate_conf = (vehicle.plate.confidence
                      if vehicle.plate is not None else 0.0)

        ctx = TriggerContext(
            bbox_growth=primary_track.area_growth_ratio() if primary_track else 0.0,
            vehicle_present=vehicle.present,
            vehicle_conf=max([d.confidence for d in veh_dets], default=0.0),
            vehicle_norm_y2=(vehicle.bbox.y2 / h) if (vehicle.bbox and h) else 0.0,
            plate_roi_present=run_ocr and vehicle.present,
            plate_ocr_conf=plate_conf,
            ambiguous_object_confs=[d.confidence for d in detections
                                    if d.label in ("phone", "cigarette")],
        )
        return result, ctx
