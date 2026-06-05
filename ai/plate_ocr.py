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
    digit_map = {"O": "0", "I": "1", "S": "5", "B": "8", "Z": "2", "G": "6",
                 "J": "3", "D": "0", "Q": "0", "U": "0"}
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
    """Gamma + LANCZOS4 ölçekleme + CLAHE + bilateral + keskinleştirme."""
    try:
        import cv2
        h, w = crop.shape[:2]
        # Gamma correction for dark frames (underground parking etc.)
        mean_brightness = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).mean() if crop.ndim == 3 else crop.mean()
        if mean_brightness < 80:
            gamma = 0.35
            lut = np.array([np.clip(((i / 255.0) ** gamma) * 255, 0, 255) for i in range(256)], dtype=np.uint8)
            crop = cv2.LUT(crop, lut)
        big = cv2.resize(crop, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
        # CLAHE on luminance for low-light robustness
        gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY) if big.ndim == 3 else big
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        enh = clahe.apply(gray)
        big = cv2.cvtColor(enh, cv2.COLOR_GRAY2BGR)
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
        self._tesseract_ok = False
        self._history: deque = deque(maxlen=history)
        if self.mode == "real":
            self._init_reader()

    def _init_reader(self):
        try:
            import easyocr
            # Türk plakası yalnızca A-Z + 0-9 kullanır → "en" modeli yeterli
            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        except Exception as e:
            print(f"[PlateOCR] EasyOCR başlatılamadı: {e}")
            self.mode = "mock"
        # Tesseract yedek (easyocr düşük güven durumunda devreye girer)
        self._tesseract_ok = False
        try:
            import pytesseract as _pyt
            _pyt.get_tesseract_version()
            self._tesseract_ok = True
        except Exception:
            pass

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
        # Süper çözünürlük: geniş crop'lar da dahil (video frame'den gelen plaka bölgesi)
        if w < 200:
            crop = super_resolve(crop, scale=4)
        elif w < 500:
            crop = super_resolve(crop, scale=2)

        best_text, best_conf = None, 0.0
        allowlist = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for var in _variants(crop):
            try:
                results = self._reader.readtext(
                    var, allowlist=allowlist,
                    text_threshold=0.20, low_text=0.20, link_threshold=0.10,
                ) if self._reader else []
                if results:
                    # Sol→sağ sırala ve birleştir ("34TC" + "8532" → "34TC8532")
                    results_sorted = sorted(results, key=lambda r: r[0][0][0])
                    combined = "".join(t for _, t, _ in results_sorted if t.strip())
                    avg_conf = sum(c for _, _, c in results_sorted) / len(results_sorted)
                    if avg_conf > best_conf:
                        best_text, best_conf = combined, avg_conf
                    for _, text, conf in results:
                        if conf > best_conf:
                            best_text, best_conf = text, conf
            except Exception:
                pass

        # Tesseract yedek: EasyOCR güveni düşükse veya sonuç yoksa dene
        if self._tesseract_ok and (best_conf < 0.20 or best_text is None):
            try:
                import cv2
                import pytesseract
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
                cfg = '--psm 7 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                t = pytesseract.image_to_string(gray, config=cfg).strip()
                t = re.sub(r"[^A-Z0-9]", "", t.upper())
                if len(t) >= 5:
                    # Tesseract güven skoru doğrudan alınamıyor → sabit 0.20 ata
                    if 0.20 > best_conf:
                        best_text, best_conf = t, 0.20
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

        # Düşük eşik: video kalitesi düşük, karanlık ortam → konsensüs mekanizması kurtarır
        if not (final and is_valid_tr_plate(final) and conf >= 0.12):
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
