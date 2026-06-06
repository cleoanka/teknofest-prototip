"""
Plaka OCR — production-grade.

Düzeltilen sorunlar (v2 → v3):
  1. _LETTER_FIX str.maketrans duplicate '0' bug'ı → dict-bazlı tabloya geçildi
  2. _apply_position_rules → kör sınır tespiti yerine tüm geçerli split noktaları
     denenerek TR_PLATE_RE'ye uyan ilk sonuç seçilir (disambiguation by regex)
  3. EasyOCR allowlist → sadece Türk plakasında geçen 31 karakter
  4. GPU/MPS otomatik seçimi
  5. Upscale → min 64px yükseklik garantisi
  6. Preprocessing: CLAHE + bilateral + Otsu (4 varyant)
  7. Güven-ağırlıklı konsensüs (aynı uzunlukta okumalar hizalanır)
  8. Conf eşiği 0.55 (eski 0.70 çok agresifti)
"""
from __future__ import annotations

import os
import re
from collections import deque, Counter
from contextlib import contextmanager
from typing import List, Optional, Tuple

import numpy as np

from ai.schema import PlateResult


@contextmanager
def _easyocr_ssl_context():
    """EasyOCR model indirmesi için SSL sertifikasını GÜVENLİ ayarla.

    Eski kod modül seviyesinde `ssl._create_default_https_context =
    ssl._create_unverified_context` yapıyordu → import zinciri (backend → pipeline →
    plate_ocr) yüzünden TÜM sürecin HTTPS doğrulaması kapanıyordu (webhook, dış API,
    CAMARA QoD dahil). MITM açığı. Burada doğrulamayı KAPATMIYORUZ; sadece certifi
    CA paketini bu Reader oluşturma bloğu için ortama veriyoruz (varsa).
    """
    try:
        import certifi
        prev_cert = os.environ.get("SSL_CERT_FILE")
        prev_req = os.environ.get("REQUESTS_CA_BUNDLE")
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
        try:
            yield
        finally:
            # Bu blok dışında ortamı bozmamak için eski değerleri geri yükle.
            for key, prev in (("SSL_CERT_FILE", prev_cert), ("REQUESTS_CA_BUNDLE", prev_req)):
                if prev is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = prev
    except Exception:
        yield

# TR plaka regex: 2 rakam (il) + 1-3 harf + 2-4 rakam
TR_PLATE_RE = re.compile(r"^(0[1-9]|[1-7][0-9]|8[01])[A-Z]{1,3}[0-9]{2,4}$")

# EasyOCR allowlist: Türk plakasında GERÇEKTEN geçen karakterler
# I, O, Q, W, X → Türk plakasında kullanılmıyor; çıkarıldı
_PLATE_ALLOWLIST = "ABCDEFGHJKLMNPRSTUVYZ0123456789"

_DIGITS = set("0123456789")
_LETTERS = set("ABCDEFGHJKLMNPRSTUVYZ")

# Karakter karmaşası düzeltme — dict bazlı (str.maketrans duplicate sorunu yok)
# Rakam pozisyonunda harf → rakama çevir
_OCR_TO_DIGIT: dict[str, str] = {
    'O': '0', 'I': '1', 'B': '8', 'S': '5',
    'Z': '2', 'G': '6', 'T': '7', 'A': '4',
}
# Harf pozisyonunda rakam → harfe çevir
_OCR_TO_LETTER: dict[str, str] = {
    '0': 'O', '1': 'I', '8': 'B', '5': 'S',
    '2': 'Z', '6': 'G', '7': 'T', '4': 'A',
}

# Minimum boyutlar: bu altında OCR anlamsız
MIN_PLATE_WIDTH = 60
MIN_PLATE_HEIGHT = 20
# 64→96: daha yüksek çözünürlük 3/0 ve 8/B gibi OCR karmaşalarını önemli ölçüde azaltır.
TARGET_PLATE_HEIGHT = 96


def normalize_plate(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def is_valid_tr_plate(text: str) -> bool:
    return bool(TR_PLATE_RE.match(normalize_plate(text)))


def _apply_position_rules(text: str) -> str:
    """
    Türk plaka yapısına göre karakter düzeltme.

    Strateji: tüm geçerli split noktalarını (1,2,3 harf) dener; regex'e uyan
    ilk sonucu döndürür. 3↔0 karmaşası: il kodunun ilk hanesi için her iki
    varyant da sınanır — geçerli plaka üreteni tercih eder.
    """
    if len(text) < 5:
        return text

    def fix_digit(c: str) -> str:
        return _OCR_TO_DIGIT.get(c, c)

    def fix_letter(c: str) -> str:
        return _OCR_TO_LETTER.get(c, c)

    # İl kodu: pozisyon 0-1 her zaman rakam
    il = "".join(fix_digit(c) for c in text[:2])

    # 3↔0 karmaşası için alternatif il kodu (OCR sık karıştırır).
    # Her iki varyantı da geçerliyse sınayla — formatla eşleşen kazanır.
    il_alt = ({"0": "3", "3": "0"}.get(il[0], il[0]) + il[1]) if il else il
    il_variants = [il] if il == il_alt else [il, il_alt]

    best_candidate = None
    for il_try in il_variants:
        for n_letters in (1, 2, 3):
            letter_end = 2 + n_letters
            if letter_end >= len(text):
                continue
            harf = "".join(fix_letter(c) for c in text[2:letter_end])
            sayi = "".join(fix_digit(c) for c in text[letter_end:])
            candidate = il_try + harf + sayi
            if is_valid_tr_plate(candidate):
                return candidate
            if best_candidate is None:
                best_candidate = candidate

    return best_candidate or text


def _char_vote(candidates: List[Tuple[str, float]]) -> Tuple[Optional[str], float]:
    """En iyi adayın uzunluğunu çapa alarak ağırlıklı karakter oylaması.

    Neden çapa: farklı uzunluktaki okumaları (8 vs 9 karakter) birleştirmek
    anlamsız karakter zinciri üretir. En yüksek skorlu okumanın uzunluğu referans
    alınır; sadece aynı uzunluktaki diğer adaylar oylamaya katılır.
    """
    if not candidates:
        return None, 0.0
    best_text, best_score = max(candidates, key=lambda x: x[1])
    target_len = len(best_text)
    same_len = [(t, s) for t, s in candidates if len(t) == target_len]

    if len(same_len) < 2:
        return best_text, best_score   # oylama yapacak yeterli aday yok

    chars = []
    for i in range(target_len):
        weights: dict = {}
        for t, s in same_len:
            ch = t[i]
            weights[ch] = weights.get(ch, 0.0) + s
        chars.append(max(weights, key=weights.get))
    voted = "".join(chars)
    avg_score = sum(s for _, s in same_len) / len(same_len)
    return voted, min(avg_score, 1.0)


def _upscale(img: np.ndarray) -> np.ndarray:
    """Plaka crop'unu TARGET_PLATE_HEIGHT yüksekliğine orantılı ölçekler."""
    try:
        import cv2
        h, w = img.shape[:2]
        if h < 4 or w < 4:
            return img
        if h < TARGET_PLATE_HEIGHT:
            scale = TARGET_PLATE_HEIGHT / h
            new_w = max(1, int(w * scale))
            img = cv2.resize(img, (new_w, TARGET_PLATE_HEIGHT),
                             interpolation=cv2.INTER_CUBIC)
    except Exception:
        pass
    return img


def _preprocess_variants(crop: np.ndarray) -> List[np.ndarray]:
    """
    Plakaya özel 4 preprocessing varyantı:
      v0: orijinal (upscale)
      v1: CLAHE gri → renk
      v2: bilateral + Otsu binary → renk  (parlak gündüz, siyah-beyaz plaka)
      v3: v2 ters                          (koyu zemin, sarı harf)
    """
    base = _upscale(crop)
    out = [base]
    try:
        import cv2
        gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY) if base.ndim == 3 else base.copy()

        # v1: CLAHE
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(gray)
        out.append(cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR))

        # v2: bilateral + Otsu — ince karakterleri kalınlaştırır
        blurred = cv2.bilateralFilter(gray, 9, 75, 75)
        _, binary = cv2.threshold(blurred, 0, 255,
                                  cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.dilate(binary, kernel, iterations=1)
        out.append(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))

        # v3: ters (açık zemin koyu yazı ↔ koyu zemin açık yazı)
        out.append(cv2.cvtColor(255 - binary, cv2.COLOR_GRAY2BGR))
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


def _detect_easyocr_device() -> bool:
    """MPS (Apple Silicon) veya CUDA varsa True döndür."""
    try:
        import torch
        if torch.cuda.is_available():
            return True
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return True
    except Exception:
        pass
    return False


class PlateReader:
    def __init__(self, mode: str = "auto", history: int = 10):
        self.mode = self._resolve(mode)
        self._reader = None
        # history: (normalized_text, conf) tuple'ları
        self._history: deque[Tuple[str, float]] = deque(maxlen=history)
        if self.mode == "real":
            try:
                import easyocr
                with _easyocr_ssl_context():
                    self._reader = easyocr.Reader(
                        ["en"],
                        gpu=_detect_easyocr_device(),
                    )
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

    def _read_variants(self, crop: np.ndarray) -> Tuple[Optional[str], float]:
        """Tüm preprocessing varyantları üzerinde EasyOCR çalıştır.

        4 varyant üzerinden TÜÜM geçerli adayları toplar, ardından karakter oylaması
        (_char_vote) ile tek sonuca indirir. Bu sayede tek bir varyantın 3↔0 gibi
        anlık karakter hatası genel sonucu bozmaz.
        """
        if self.mode == "mock" or self._reader is None:
            return None, 0.0

        all_valid: List[Tuple[str, float]] = []   # geçerli TR formatı adaylar
        all_cands: List[Tuple[str, float]] = []   # format uymasa da best-effort

        for variant in _preprocess_variants(crop):
            sharpness_w = min(1.0, _laplacian_sharpness(variant) / 800.0)
            try:
                results = self._reader.readtext(
                    variant,
                    allowlist=_PLATE_ALLOWLIST,
                    detail=1,
                    paragraph=False,
                )
            except Exception:
                continue

            for _, text, conf in results:
                norm = normalize_plate(text)
                if len(norm) < 5:
                    continue
                corrected = _apply_position_rules(norm)
                format_bonus = 0.12 if is_valid_tr_plate(corrected) else 0.0
                score = conf * (0.55 + 0.45 * sharpness_w) + format_bonus
                all_cands.append((corrected, score))
                if is_valid_tr_plate(corrected):
                    all_valid.append((corrected, score))

        # Geçerli adaylar varsa karakter oylamasıyla birleştir.
        if all_valid:
            voted, score = _char_vote(all_valid)
            if voted and is_valid_tr_plate(voted):
                return voted, score
            # Oylamanın ürettiği metin geçersizse (oylama sınır bölgede bozabilir)
            # en yüksek skorlu geçerli adayı döndür
            return max(all_valid, key=lambda x: x[1])

        if all_cands:
            return max(all_cands, key=lambda x: x[1])

        return None, 0.0

    def read(self, crop: Optional[np.ndarray]) -> PlateResult:
        if crop is None or crop.size == 0:
            return PlateResult()

        h, w = crop.shape[:2]
        if w < MIN_PLATE_WIDTH or h < MIN_PLATE_HEIGHT:
            return PlateResult()

        text, conf = self._read_variants(crop)
        norm = text or ""

        if norm and is_valid_tr_plate(norm):
            self._history.append((norm, conf))

        # Konsensüs: geçmiş okumaların güven-ağırlıklı karakter çoğunluğu
        consensus, c_conf = self._weighted_consensus()

        if consensus and is_valid_tr_plate(consensus):
            final_text, final_conf = consensus, c_conf
        elif norm and is_valid_tr_plate(norm):
            final_text, final_conf = norm, conf
        else:
            return PlateResult()

        if final_conf < 0.45:
            return PlateResult()

        return PlateResult(
            text=final_text,
            confidence=round(final_conf, 3),
            valid_format=True,
        )

    def _weighted_consensus(self) -> Tuple[Optional[str], float]:
        """
        Geçmişten yalnız geçerli okumaları al.
        Aynı uzunluktaki okumaları güven-ağırlıklı karakter çoğunluğu ile birleştir.
        """
        valid = [(t, c) for t, c in self._history if is_valid_tr_plate(t)]
        if not valid:
            return None, 0.0

        # En yaygın uzunluğu seç
        target_len = Counter(len(t) for t, _ in valid).most_common(1)[0][0]
        same_len = [(t, c) for t, c in valid if len(t) == target_len]

        if not same_len:
            best = max(valid, key=lambda x: x[1])
            return best

        chars = []
        for i in range(target_len):
            weights: dict[str, float] = {}
            for text, c in same_len:
                ch = text[i]
                weights[ch] = weights.get(ch, 0.0) + c
            chars.append(max(weights, key=weights.get))

        avg_conf = sum(c for _, c in same_len) / len(same_len)
        return "".join(chars), round(avg_conf, 3)
