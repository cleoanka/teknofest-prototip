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


def _region_brightness(frame: np.ndarray, rx: int, ry: int, rw: int, rh: int) -> float:
    """Bölgenin ortalama parlaklığını döner."""
    try:
        import cv2
        h, w = frame.shape[:2]
        x1, y1 = max(0, rx), max(0, ry)
        x2, y2 = min(w, rx + rw), min(h, ry + rh)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return 0.0
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        return float(gray.mean())
    except Exception:
        return 0.0


def _detect_cv(frame: np.ndarray) -> List[BBox]:
    """
    OpenCV tabanlı plaka aday tespiti — CLAHE ön işlemli, lokal kontrast tabanlı.

    Sorun: Yeraltı otoparkı gibi düşük ışıklı sahnelerde ham piksel değerleri
    20-30 aralığında kalır; sabit parlıklık eşiği (>140) hiçbir aday bulamaz.

    Çözüm: CLAHE (Contrast Limited Adaptive Histogram Equalization) uygulanır.
    CLAHE her yerel bölgede kontrastı 0-255'e normalize eder — beyaz plaka,
    koyu araç gövdesine karşı belirgin hale gelir (mutlak parlaklıktan bağımsız).
    """
    try:
        import cv2
    except ImportError:
        return []

    h, w = frame.shape[:2]
    min_area = w * h * 0.0003
    max_area = w * h * 0.08
    candidates: List[BBox] = []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame.copy()

    # CLAHE: lokal kontrast güçlendirme (düşük ışık koşulları için kritik)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    def _check(rx: int, ry: int, rw: int, rh: int) -> bool:
        if rw < 40 or rh < 10:
            return False
        area = rw * rh
        if not (min_area <= area <= max_area):
            return False
        if not (2.5 <= rw / rh <= 8.5):
            return False
        region = enhanced[max(0, ry):min(h, ry + rh), max(0, rx):min(w, rx + rw)]
        return region.size > 0 and float(region.mean()) >= 120

    # ── Yöntem 1: CLAHE görüntüsünde sabit eşik (birincil) ─────────────────
    for thresh_val in [200, 180, 160, 140]:
        _, binary = cv2.threshold(enhanced, thresh_val, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 6))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            rx, ry, rw, rh = cv2.boundingRect(c)
            if _check(rx, ry, rw, rh):
                candidates.append(BBox(x1=float(rx), y1=float(ry),
                                       x2=float(rx + rw), y2=float(ry + rh)))

    # ── Yöntem 2: Otsu adaptif eşik (ışık değişimine dayanıklı) ─────────────
    _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (22, 5))
    closed2 = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel2)
    cnts2, _ = cv2.findContours(closed2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        rx, ry, rw, rh = cv2.boundingRect(c)
        if _check(rx, ry, rw, rh):
            candidates.append(BBox(x1=float(rx), y1=float(ry),
                                   x2=float(rx + rw), y2=float(ry + rh)))

    # ── Yöntem 3: Canny kenar + kontur (ikincil) ─────────────────────────────
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    dil_k = cv2.getStructuringElement(cv2.MORPH_RECT, (18, 3))
    dilated = cv2.dilate(edges, dil_k)
    cnts3, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts3:
        rx, ry, rw, rh = cv2.boundingRect(c)
        if _check(rx, ry, rw, rh):
            candidates.append(BBox(x1=float(rx), y1=float(ry),
                                   x2=float(rx + rw), y2=float(ry + rh)))

    return _nms(candidates)[:5]


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
