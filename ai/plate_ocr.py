"""
Plaka OCR — çok-varyantlı okuma + keskinlik ağırlıklı konsensüs.

Gerçek mod: EasyOCR (kurulu ise). Mock mod: deterministik sahte plaka üretir.
ÖTR'deki "Adaptive Y-Crop + Multi-Variant OCR + Keskinlik Ağırlıklı Konsensüs"
fikrinin sadeleştirilmiş, çalışan uygulaması.
"""
from __future__ import annotations

import re
from collections import deque, Counter
from typing import List, Optional, Tuple

import numpy as np

from ai.schema import PlateResult

# TR plaka: 2 il kodu + 1-3 harf + 2-4 rakam  (boşluklar normalize edilir)
TR_PLATE_RE = re.compile(r"^(0[1-9]|[1-7][0-9]|8[01])[A-Z]{1,3}[0-9]{2,4}$")


def normalize_plate(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def is_valid_tr_plate(text: str) -> bool:
    return bool(TR_PLATE_RE.match(normalize_plate(text)))


def _variants(crop: np.ndarray) -> List[np.ndarray]:
    """orijinal + CLAHE/kontrast + ters — OCR'ı zorlu ışıkta dayanıklı kılar."""
    out = [crop]
    try:
        import cv2
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        out.append(cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR))
        out.append(cv2.cvtColor(255 - clahe, cv2.COLOR_GRAY2BGR))
    except Exception:
        pass
    return out


def _laplacian_sharpness(img: np.ndarray) -> float:
    try:
        import cv2
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return float(np.var(img))


class PlateReader:
    def __init__(self, mode: str = "auto", history: int = 8):
        self.mode = self._resolve(mode)
        self._reader = None
        self._history: deque = deque(maxlen=history)
        if self.mode == "real":
            try:
                import easyocr
                self._reader = easyocr.Reader(["en"], gpu=False)
            except Exception:
                self.mode = "mock"

    @staticmethod
    def _resolve(mode: str) -> str:
        mode = (mode or "auto").lower()
        if mode in ("real", "mock"):
            return mode
        try:
            import easyocr  # noqa: F401
            return "real"
        except Exception:
            return "mock"

    def _read_once(self, crop: np.ndarray) -> Tuple[Optional[str], float]:
        if self.mode == "mock" or self._reader is None:
            return None, 0.0
        best_text, best_conf = None, 0.0
        for var in _variants(crop):
            w = min(1.0, _laplacian_sharpness(var) / 500.0)
            for _, text, conf in self._reader.readtext(var):
                eff = conf * (0.7 + 0.3 * w)
                if eff > best_conf:
                    best_text, best_conf = text, eff
        return best_text, best_conf

    def read(self, crop: Optional[np.ndarray]) -> PlateResult:
        if crop is None or crop.size == 0:
            return PlateResult()
        text, conf = self._read_once(crop)
        norm = normalize_plate(text) if text else ""
        if norm and is_valid_tr_plate(norm):
            self._history.append(norm)
        # Pozisyon-bazlı çoğunluk konsensüsü (son N okuma)
        consensus = self._consensus()
        final = consensus or norm
        # Geçerli TR formatı + yüksek güven olmadan gösterme
        if not (final and is_valid_tr_plate(final) and conf >= 0.70):
            return PlateResult()
        return PlateResult(
            text=final,
            confidence=round(conf, 3),
            valid_format=True,
        )

    def _consensus(self) -> Optional[str]:
        if not self._history:
            return None
        maxlen = max(len(p) for p in self._history)
        chars = []
        for i in range(maxlen):
            col = [p[i] for p in self._history if i < len(p)]
            if col:
                chars.append(Counter(col).most_common(1)[0][0])
        return "".join(chars) if chars else None
