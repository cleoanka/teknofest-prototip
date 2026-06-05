"""
Plaka OCR — süper çözünürlük + çok-varyantlı okuma + konsensüs.

Gerçek mod: EasyOCR. Mock mod: yalnızca None döner (sahte plaka üretmez).
SSL hatası Python 3.13'te modül seviyesinde yamalanır.
"""
from __future__ import annotations

import re
import ssl
from collections import deque, Counter
from typing import List, Optional, Tuple

import numpy as np

from ai.schema import PlateResult

# Python 3.13 SSL sertifika hatası düzeltme (EasyOCR model indirme)
ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore[attr-defined]

# TR plaka: 2 il kodu + 1-3 harf + 2-4 rakam (34TC8532 gibi)
TR_PLATE_RE = re.compile(r"^(0[1-9]|[1-7][0-9]|8[01])[A-Z]{1,3}[0-9]{2,4}$")


def normalize_plate(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def ocr_corrections(text: str) -> str:
    """Yaygın OCR hataları: O↔0, I↔1, S↔5, B↔8 (pozisyona göre)."""
    if not text or len(text) < 5:
        return text
    t = list(text)
    digit_map = {"O": "0", "I": "1", "S": "5", "B": "8", "Z": "2", "G": "6"}
    alpha_map = {"0": "O", "1": "I", "5": "S", "8": "B"}

    # İlk 2 karakter (il kodu) → rakam olmalı
    for i in range(min(2, len(t))):
        t[i] = digit_map.get(t[i], t[i])

    # Son 2-4 karakteri rakama çevir (number suffix)
    # Sayı bloğu son konumdan itibaren
    j = len(t) - 1
    digit_count = 0
    while j >= 2 and t[j].isdigit() or (j >= 2 and t[j] in digit_map):
        t[j] = digit_map.get(t[j], t[j])
        digit_count += 1
        j -= 1

    return "".join(t)


def is_valid_tr_plate(text: str) -> bool:
    return bool(TR_PLATE_RE.match(normalize_plate(text)))


def super_resolve(crop: np.ndarray, scale: int = 4) -> np.ndarray:
    """LANCZOS4 ölçekleme + bilateral filtre + keskinleştirme."""
    try:
        import cv2
        h, w = crop.shape[:2]
        big = cv2.resize(crop, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
        filtered = cv2.bilateralFilter(big, 9, 75, 75)
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]], dtype=np.float32)
        return cv2.filter2D(filtered, -1, kernel)
    except Exception:
        return crop


def _variants(crop: np.ndarray) -> List[np.ndarray]:
    """Orijinal + CLAHE + ters — farklı ışık koşullarında OCR güvenilirliği."""
    out = [crop]
    try:
        import cv2
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(gray)
        out.append(cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR))
        out.append(cv2.cvtColor(255 - gray, cv2.COLOR_GRAY2BGR))
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
            self._init_reader()

    def _init_reader(self):
        try:
            import easyocr
            # tr dili ekle: Türk plakasındaki karakterler için
            self._reader = easyocr.Reader(["en", "tr"], gpu=False, verbose=False)
        except Exception as e:
            print(f"[PlateOCR] EasyOCR başlatılamadı: {e}")
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

        h, w = crop.shape[:2]
        # Küçük plateler için süper çözünürlük (LP detector crop'u bile bazen 60-80px olur)
        if w < 120:
            crop = super_resolve(crop, scale=4)
        elif w < 240:
            crop = super_resolve(crop, scale=2)

        best_text, best_conf = None, 0.0
        allowlist = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for var in _variants(crop):
            w_sharp = min(1.0, _laplacian_sharpness(var) / 300.0)
            try:
                results = self._reader.readtext(var, allowlist=allowlist)
                for _, text, conf in results:
                    eff = conf * (0.6 + 0.4 * w_sharp)
                    if eff > best_conf:
                        best_text, best_conf = text, eff
            except Exception:
                pass
        return best_text, best_conf

    def read(self, crop: Optional[np.ndarray]) -> PlateResult:
        if crop is None or crop.size == 0:
            return PlateResult()

        text, conf = self._read_once(crop)
        norm = normalize_plate(text) if text else ""
        corrected = ocr_corrections(norm)

        for candidate in [corrected, norm]:
            if candidate and is_valid_tr_plate(candidate):
                self._history.append(candidate)
                norm = candidate
                break

        consensus = self._consensus()
        final = consensus or norm

        # LP detector tarafından kesilmiş bölgede güven eşiği biraz daha düşük olabilir
        if not (final and is_valid_tr_plate(final) and conf >= 0.45):
            return PlateResult()

        return PlateResult(text=final, confidence=round(conf, 3), valid_format=True)

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
