"""
Plaka tespiti — iki katmanlı yaklaşım.

Kullanım: pipeline her zaman araç crop'unu geçirir (full frame değil).
Bu sayede trafik levhası / duvar gibi yanlış tespitler tamamen önlenir.

Katman 1 — YOLO plaka modeli (yerel .pt veya opt-in indirme):
  - LP_MODEL_PATH=/path/to/model.pt  → doğrudan yerel model
  - LP_HF_DOWNLOAD=1                 → HuggingFace'den indirme dener
  - Hiçbiri yoksa → katman 2'ye düşer (ağ çağrısı yapılmaz)

Katman 2 — OpenCV CV fallback (CLAHE + kontur):
  - Model olmadan her koşulda çalışır
  - Araç crop üzerinde çalışınca false positive oranı düşer

Mock mod — AI_MODE=mock veya LP_MOCK=1:
  - Tüm tespitler atlanır, [] döner
  - CI/test için ağsız ve modelsiz çalışma garantisi
"""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

import numpy as np

from ai.schema import BBox

# HuggingFace opt-in indirme — LP_HF_DOWNLOAD=1 ile etkinleştirilir
_HF_REPOS = [
    ("keremberke/yolov8n-license-plate-detection", "best.pt"),
    ("nickmuchi/yolov5-base-plates-detection", "best.pt"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcı fonksiyonlar (CV fallback için)
# ─────────────────────────────────────────────────────────────────────────────

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
    sorted_b = sorted(bboxes, key=lambda b: b.area, reverse=True)
    kept: List[BBox] = []
    for b in sorted_b:
        if all(_iou(b, k) < iou_thr for k in kept):
            kept.append(b)
    return kept


def _detect_cv(frame: np.ndarray) -> List[BBox]:
    """
    OpenCV tabanlı plaka aday tespiti — CLAHE ön işlemli.

    Araç crop üzerinde çalışınca false positive oranı düşer:
    crop dışındaki trafik levhası, duvar vb. zaten görünmüyor.
    Düşük ışık (yeraltı otoparkı) için CLAHE kritik: ham piksel yerine
    lokal kontrast normalize ederek beyaz plakayı koyu araç gövdesinden ayırır.
    """
    try:
        import cv2
    except ImportError:
        return []

    h, w = frame.shape[:2]
    min_area = w * h * 0.0003
    max_area = w * h * 0.10
    candidates: List[BBox] = []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame.copy()
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    def _check(rx: int, ry: int, rw: int, rh: int) -> bool:
        if rw < 30 or rh < 8:
            return False
        area = rw * rh
        if not (min_area <= area <= max_area):
            return False
        # Türk standart plakası oranı ~4.64:1; geniş tolerans perspektif için
        if not (2.8 <= rw / rh <= 7.0):
            return False
        region = enhanced[max(0, ry):min(h, ry + rh), max(0, rx):min(w, rx + rw)]
        return region.size > 0 and float(region.mean()) >= 100

    # Yöntem 1: Sabit eşik (birincil)
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

    # Yöntem 2: Otsu (ışık değişimine dayanıklı)
    _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (22, 5))
    closed2 = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, kernel2)
    cnts2, _ = cv2.findContours(closed2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts2:
        rx, ry, rw, rh = cv2.boundingRect(c)
        if _check(rx, ry, rw, rh):
            candidates.append(BBox(x1=float(rx), y1=float(ry),
                                   x2=float(rx + rw), y2=float(ry + rh)))

    # Yöntem 3: Canny kenar + kontur
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


# ─────────────────────────────────────────────────────────────────────────────
# LicensePlateDetector
# ─────────────────────────────────────────────────────────────────────────────

class LicensePlateDetector:
    def __init__(self, mode: str = "auto"):
        """
        mode: "auto" | "real" | "mock"
        mock modda model yükleme ve CV fallback atlanır; detect() [] döner.
        """
        self._model = None
        self._using_model = False
        self._mock = self._resolve_mock(mode)
        if not self._mock:
            self._try_load_model()

    @staticmethod
    def _resolve_mock(mode: str) -> bool:
        if (mode or "").lower() == "mock":
            return True
        if os.environ.get("LP_MOCK", "").lower() in ("1", "true", "yes"):
            return True
        try:
            from config.settings import get_settings
            return get_settings().lp_mock
        except Exception:
            return False

    def _try_load_model(self):
        """
        Öncelik:
          1) settings.lp_model_path / LP_MODEL_PATH env (yerel .pt)
          2) ~/.cache/teknofest/lp_yolo.pt (önceden önbelleklenmiş)
          3) HuggingFace indirme — sadece lp_hf_download=True / LP_HF_DOWNLOAD=1
          Hiçbiri yoksa CV fallback aktif, ağ çağrısı yapılmaz.
        """
        try:
            from ultralytics import YOLO
        except Exception as e:
            print(f"[LP Detector] ultralytics yok → CV fallback: {type(e).__name__}")
            return

        cache_dir = os.path.expanduser("~/.cache/teknofest")
        cache_path = os.path.join(cache_dir, "lp_yolo.pt")

        # 1) Açık yerel model yolu
        try:
            from config.settings import get_settings
            s = get_settings()
            env_path = s.lp_model_path or os.environ.get("LP_MODEL_PATH", "")
            hf_enabled = s.lp_hf_download or os.environ.get("LP_HF_DOWNLOAD") == "1"
        except Exception:
            env_path = os.environ.get("LP_MODEL_PATH", "")
            hf_enabled = os.environ.get("LP_HF_DOWNLOAD") == "1"

        if env_path:
            if os.path.exists(env_path):
                cache_path = env_path
            else:
                print(f"[LP Detector] LP_MODEL_PATH bulunamadı: {env_path}")
                return

        # 2) HF indirme (opt-in)
        elif not os.path.exists(cache_path) and hf_enabled:
            self._try_hf_download(cache_path)

        # 3) Modeli yükle
        if os.path.exists(cache_path):
            try:
                self._model = YOLO(cache_path)
                self._using_model = True
                print(f"[LP Detector] YOLOv8 model aktif: {cache_path}")
            except Exception as e:
                print(f"[LP Detector] Model yüklenemedi → CV fallback: {type(e).__name__}")
        else:
            print("[LP Detector] Yerel model yok → CV fallback aktif.")

    def _try_hf_download(self, cache_path: str) -> None:
        try:
            from huggingface_hub import hf_hub_download
            import shutil
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            for repo_id, filename in _HF_REPOS:
                try:
                    print(f"[LP Detector] İndiriliyor: {repo_id}")
                    dl = hf_hub_download(repo_id=repo_id, filename=filename)
                    shutil.copy(dl, cache_path)
                    print(f"[LP Detector] Önbelleklendi: {cache_path}")
                    return
                except Exception as e:
                    print(f"[LP Detector] {repo_id} başarısız: {type(e).__name__}")
        except Exception as e:
            print(f"[LP Detector] HF indirme atlandı: {type(e).__name__}")

    @property
    def available(self) -> bool:
        return True  # Mock dahil her zaman çalışır ([] döner)

    def detect(self, frame: np.ndarray, conf: Optional[float] = None) -> List[BBox]:
        """
        frame: araç crop (tercih) veya full frame.
        conf: None ise settings.lp_conf kullanılır (varsayılan 0.20).
        """
        if self._mock or frame is None or frame.size == 0:
            return []

        _conf: float
        if conf is not None:
            _conf = conf
        else:
            try:
                from config.settings import get_settings
                _conf = get_settings().lp_conf
            except Exception:
                _conf = 0.20

        if self._using_model and self._model is not None:
            try:
                results = self._model.predict(frame, conf=_conf, verbose=False)[0]
                bboxes: List[BBox] = []
                if results.boxes:
                    for b in results.boxes:
                        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]
                        if (x2 - x1) < 20 or (y2 - y1) < 8:
                            continue
                        bboxes.append(BBox(x1=x1, y1=y1, x2=x2, y2=y2))
                return bboxes
            except Exception:
                pass

        return _detect_cv(frame)

    def detect_best(self, frame: np.ndarray, conf: Optional[float] = None) -> Optional[BBox]:
        bboxes = self.detect(frame, conf=conf)
        return max(bboxes, key=lambda b: b.area) if bboxes else None


# ─────────────────────────────────────────────────────────────────────────────
# Singleton — mock modu için önbellekleme atlanır
# ─────────────────────────────────────────────────────────────────────────────

_lp_detector: Optional[LicensePlateDetector] = None


def get_lp_detector(mode: str = "auto") -> LicensePlateDetector:
    global _lp_detector
    # Mock: ucuz nesne, önbelleğe almaya gerek yok
    if LicensePlateDetector._resolve_mock(mode):
        return LicensePlateDetector(mode="mock")
    if _lp_detector is None:
        _lp_detector = LicensePlateDetector(mode=mode)
    return _lp_detector


def reset_lp_detector() -> None:
    """Test izolasyonu için singleton'ı sıfırla."""
    global _lp_detector
    _lp_detector = None
