"""
Nesne tespit katmanı.

- AI_MODE=real / auto(+ultralytics kurulu): gerçek YOLOv8 çıkarımı (COCO ön-eğitimli).
  Mac'te ultralytics otomatik MPS (Apple Silicon) kullanır.
- AI_MODE=mock / auto(ultralytics yok): numpy tabanlı deterministik mock dedektör.
  Mock dedektör, sentetik test videosundaki parlak araç bloğunu eşikleme ile bulur;
  böylece tüm hat ve testler model olmadan da uçtan uca çalışır.

COCO ön-eğitimli model 'cigarette' gibi sınıfları bilmez; bunlar ai/training ile
fine-tune sonrası eklenir. Mock mod, demo/test için bu sınıfları kural ile üretebilir.
"""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np

from ai.schema import Detection, BBox
from config.settings import get_settings, CANONICAL_MAP


def _ultralytics_available() -> bool:
    try:
        import ultralytics  # noqa: F401
        return True
    except Exception:
        return False


def resolve_mode(settings) -> str:
    mode = settings.ai_mode.lower()
    if mode == "real":
        return "real"
    if mode == "mock":
        return "mock"
    # auto
    return "real" if _ultralytics_available() else "mock"


class BaseDetector:
    def detect(self, frame: np.ndarray, conf: float, profile: str) -> List[Detection]:
        raise NotImplementedError


# ──────────────────────────────────────────────────────────────────────────────
# Gerçek YOLO dedektörü
# ──────────────────────────────────────────────────────────────────────────────
class YoloDetector(BaseDetector):
    def __init__(self, model_normal: str, model_critical: str, device: str = "auto"):
        from ultralytics import YOLO  # lazy import
        self._device = self._resolve_device(device)
        self._models = {
            "normal": YOLO(model_normal),
            "critical": YOLO(model_critical),
        }
        self._names = self._models["normal"].names

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def detect(self, frame: np.ndarray, conf: float, profile: str) -> List[Detection]:
        model = self._models["critical" if profile == "critical" else "normal"]
        s = get_settings()
        res = model.predict(
            frame, conf=conf, iou=s.iou_nms, device=self._device, verbose=False
        )[0]
        out: List[Detection] = []
        names = res.names if hasattr(res, "names") else self._names
        if res.boxes is None:
            return out
        for b in res.boxes:
            cls_id = int(b.cls[0])
            raw_name = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else names[cls_id]
            mapped = CANONICAL_MAP.get(raw_name)
            if mapped is None:
                continue
            canonical, vtype = mapped       # araç alt-tipi → ("vehicle", "car"/"minibus"/...)
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
            attrs = {"vtype": vtype} if vtype else {}
            out.append(Detection(
                label=canonical,
                confidence=float(b.conf[0]),
                bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
                attributes=attrs,
            ))
        return out


# ──────────────────────────────────────────────────────────────────────────────
# Mock dedektör (numpy-only, deterministik) — model yokken hattı ayakta tutar
# ──────────────────────────────────────────────────────────────────────────────
class MockDetector(BaseDetector):
    """
    Sentetik kareyi analiz eder: koyu arka plan üzerinde en parlak dikdörtgensel
    bölgeyi 'vehicle' kabul eder. Kritik profilde, aracın içinde küçük 'phone'/
    'person' kutuları kural ile üretilir (yüksek bant -> daha çok detay metaforu).
    """

    def detect(self, frame: np.ndarray, conf: float, profile: str) -> List[Detection]:
        if frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        gray = frame.mean(axis=2) if frame.ndim == 3 else frame
        thr = max(60.0, gray.mean() + gray.std())
        ys, xs = np.where(gray > thr)
        dets: List[Detection] = []
        if xs.size > 30:
            x1, x2 = float(xs.min()), float(xs.max())
            y1, y2 = float(ys.min()), float(ys.max())
            area_ratio = ((x2 - x1) * (y2 - y1)) / (w * h)
            # alan oranına göre güven (yaklaştıkça artar) — QoD demosu için ideal
            vconf = float(min(0.95, 0.45 + area_ratio * 1.2))
            dets.append(Detection(
                label="vehicle",
                confidence=round(vconf, 3),
                bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
                attributes={"vtype": "car"},
            ))
            # Kritik profilde araç içi nesneleri kural ile üret
            if profile == "critical" and area_ratio > 0.06:
                cw, ch = (x2 - x1), (y2 - y1)
                dets.append(Detection(
                    label="person",
                    confidence=0.8,
                    bbox=BBox(x1=x1 + 0.15 * cw, y1=y1 + 0.2 * ch,
                              x2=x1 + 0.55 * cw, y2=y2 - 0.1 * ch),
                ))
                if int((frame.sum()) % 2) == 0:  # deterministik "telefon var" senaryosu
                    dets.append(Detection(
                        label="phone",
                        confidence=0.72,
                        bbox=BBox(x1=x1 + 0.30 * cw, y1=y1 + 0.35 * ch,
                                  x2=x1 + 0.42 * cw, y2=y1 + 0.55 * ch),
                    ))
        return dets


def build_detector(settings=None) -> BaseDetector:
    settings = settings or get_settings()
    mode = resolve_mode(settings)
    if mode == "real":
        try:
            return YoloDetector(
                settings.yolo_model_normal,
                settings.yolo_model_critical,
                settings.yolo_device,
            )
        except Exception as e:  # model indirilemedi/torch yok -> mock'a düş
            os.environ.setdefault("AI_FALLBACK_REASON", str(e))
            return MockDetector()
    return MockDetector()
