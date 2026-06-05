"""
Plaka tespiti — iki katmanlı yaklaşım:

1. Model (HuggingFace) — mevcut ve erişilebilirse indirilir.
2. CV fallback — kenar + kontur tabanlı, model indirmeden çalışır.
   Türk plakası oranı (~4.7:1), beyaz zemin + kenar kontrastı kullanılır.

Araç tespitinden bağımsız çalışır: TOGG gibi COCO'nun tanımadığı araçlarda
araç bbox olmasa bile plaka konumu bulunabilir.
"""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np

from ai.schema import BBox

# HuggingFace'de denenecek modeller (sırayla)
_HF_REPOS = [
    ("keremberke/yolov8n-license-plate-detection", "best.pt"),
]


def _iou(a: BBox, b: BBox) -> float:
    ix1 = max(a.x1, b.x1); iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2); iy2 = min(a.y2, b.y2)
    iw = max(0, ix2 - ix1); ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    ua = a.area + b.area - inter
    return inter / ua if ua > 0 else 0.0


def _nms(bboxes: List[BBox], iou_thr: float = 0.4) -> List[BBox]:
    """Basit greedy NMS — büyük bbox önce alınır."""
    sorted_b = sorted(bboxes, key=lambda b: b.area, reverse=True)
    kept: List[BBox] = []
    for b in sorted_b:
        if all(_iou(b, k) < iou_thr for k in kept):
            kept.append(b)
    return kept


def _detect_cv(frame: np.ndarray) -> List[BBox]:
    """
    OpenCV tabanlı plaka aday tespiti.
    Türk plakası: beyaz/açık zemin, ~4.7:1 en-boy oranı, 30–110 mm yükseklik.
    İki teknik uygulanır ve birleştirilir:
    (a) Kenar + kontur yöntemi
    (b) Beyaz dikdörtgen bölge yöntemi (Türk plakaları için)
    """
    try:
        import cv2
    except ImportError:
        return []

    h, w = frame.shape[:2]
    min_area = w * h * 0.001   # kare boyutunun %0.1'i
    max_area = w * h * 0.15    # kare boyutunun %15'i
    candidates: List[BBox] = []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

    # ── (a) Kenar + kontur ──────────────────────────────────────────────────
    filtered = cv2.bilateralFilter(gray, 11, 17, 17)
    edges = cv2.Canny(filtered, 25, 180)
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.018 * peri, True)
        if len(approx) < 4:
            continue
        rx, ry, rw, rh = cv2.boundingRect(c)
        area = rw * rh
        if area < min_area or area > max_area or rh < 8:
            continue
        aspect = rw / rh
        if 2.5 <= aspect <= 8.0:
            candidates.append(BBox(x1=float(rx), y1=float(ry),
                                   x2=float(rx + rw), y2=float(ry + rh)))

    # ── (b) Parlak dikdörtgen (Türk beyaz plaka) ────────────────────────────
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 5))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    cnts2, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        rx, ry, rw, rh = cv2.boundingRect(c)
        area = rw * rh
        if area < min_area or area > max_area or rh < 8:
            continue
        aspect = rw / rh
        if 2.8 <= aspect <= 7.5:
            candidates.append(BBox(x1=float(rx), y1=float(ry),
                                   x2=float(rx + rw), y2=float(ry + rh)))

    return _nms(candidates)[:5]  # En fazla 5 aday döner


class LicensePlateDetector:
    def __init__(self):
        self._model = None
        self._using_model = False
        self._try_load_model()

    def _try_load_model(self):
        try:
            from ultralytics import YOLO
            from huggingface_hub import hf_hub_download

            cache_dir = os.path.expanduser("~/.cache/teknofest")
            cache_path = os.path.join(cache_dir, "lp_model.pt")

            if not os.path.exists(cache_path):
                os.makedirs(cache_dir, exist_ok=True)
                for repo_id, filename in _HF_REPOS:
                    try:
                        print(f"[LP Detector] İndiriliyor: {repo_id}/{filename}")
                        model_path = hf_hub_download(repo_id=repo_id, filename=filename)
                        import shutil
                        shutil.copy(model_path, cache_path)
                        print(f"[LP Detector] Önbelleklendi: {cache_path}")
                        break
                    except Exception as e:
                        print(f"[LP Detector] {repo_id} başarısız: {type(e).__name__}")
                        continue

            if os.path.exists(cache_path):
                self._model = YOLO(cache_path)
                self._using_model = True
                print("[LP Detector] YOLOv8 model aktif.")
            else:
                print("[LP Detector] Model indirilemedi → CV fallback aktif.")
        except Exception as e:
            print(f"[LP Detector] Başlatma hatası → CV fallback: {type(e).__name__}: {e}")

    @property
    def available(self) -> bool:
        return True  # Her zaman çalışır (CV fallback sayesinde)

    def detect(self, frame: np.ndarray, conf: float = 0.20) -> List[BBox]:
        """Çerçevede plaka bölgelerini tespit et."""
        if frame is None or frame.size == 0:
            return []

        if self._using_model and self._model is not None:
            try:
                results = self._model.predict(frame, conf=conf, verbose=False)[0]
                bboxes: List[BBox] = []
                if results.boxes:
                    for b in results.boxes:
                        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
                        if (x2 - x1) < 20 or (y2 - y1) < 8:
                            continue
                        bboxes.append(BBox(x1=x1, y1=y1, x2=x2, y2=y2))
                return bboxes
            except Exception:
                pass  # model başarısız → CV fallback

        # CV tabanlı fallback
        return _detect_cv(frame)

    def detect_best(self, frame: np.ndarray, conf: float = 0.20) -> Optional[BBox]:
        """En büyük (güvenilir) plakayı döner."""
        bboxes = self.detect(frame, conf=conf)
        if not bboxes:
            return None
        return max(bboxes, key=lambda b: b.area)


_lp_detector: Optional[LicensePlateDetector] = None


def get_lp_detector() -> LicensePlateDetector:
    global _lp_detector
    if _lp_detector is None:
        _lp_detector = LicensePlateDetector()
    return _lp_detector
