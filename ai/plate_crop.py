"""
Plaka crop geometrisi — "siyah çerçeveyi takip et" katmanı.

Neden var (kullanıcı isteği): Plaka crop'unun MÜKEMMEL dikdörtgen olması şart değil;
ÖNEMLİ olan plakanın gerçek **koyu (siyah) çerçevesini** kararlı biçimde takip etmek ve
OCR'a temiz, ortalanmış bir plaka göndermek. Ayrıca dedektör/CV fallback bazen trafik
levhası, far, tampon yazısı gibi **plaka olmayan** bölgeleri döndürür — bunları OCR'a
göndermeden elemek gerekir (şartname: genel/sağlam sistem, yanlış kayıt riski).

Bu modül saf cv2/numpy'dir; cv2 yoksa zarifçe girdomeyi olduğu gibi döndürür (K4 mock-first).

İçerik:
  - plate_sharpness()   : Laplacian keskinlik (en net kareyi seçmek için, Katman 2.2)
  - looks_like_plate()  : plaka-benzerlik geçidi (saçma bölgeleri ele, Katman 0.2 ruhu)
  - refine_to_frame()   : ROI içindeki koyu plaka çerçevesini bul → ona kırp (+pad)
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


def _to_gray(img: np.ndarray):
    import cv2
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def plate_sharpness(img: Optional[np.ndarray]) -> float:
    """Laplacian varyansı = keskinlik. Hareket bulanıklığı olan kareyi elemek için."""
    if img is None or img.size == 0:
        return 0.0
    try:
        import cv2
        return float(cv2.Laplacian(_to_gray(img), cv2.CV_64F).var())
    except Exception:
        return float(np.var(img))


def looks_like_plate(
    crop: Optional[np.ndarray],
    *,
    min_w: int = 40,
    min_h: int = 12,
    aspect_min: float = 1.8,
    aspect_max: float = 8.0,
    min_edge_density: float = 0.04,
    min_std: float = 18.0,
) -> bool:
    """
    Bir crop'un GERÇEKTEN plaka olup olmadığını ucuz geometrik+doku sinyalleriyle dener.

    Neden: YOLO modeli yokken CV fallback (ve bazen model) trafik levhası, far yansıması,
    düz panel gibi bölgeleri plaka sanabiliyor. Plaka imzası:
      1) En-boy oranı ~2:1 .. ~8:1 (tek/çift satır + perspektif toleransı),
      2) Düz/uniform DEĞİL — karakterler güçlü dikey kenarlar üretir (kenar yoğunluğu),
      3) Yeterli kontrast (std) — düz duvar/gökyüzü elenir.

    Eşikler gevşek tutuldu: amaç bariz çöpü elemek, gerçek plakayı kaçırmamak.
    """
    if crop is None or crop.size == 0:
        return False
    h, w = crop.shape[:2]
    if w < min_w or h < min_h:
        return False
    aspect = w / max(1.0, h)
    if not (aspect_min <= aspect <= aspect_max):
        return False
    try:
        import cv2
        gray = _to_gray(crop)
        if float(gray.std()) < min_std:        # uniform bölge (duvar, panel) → plaka değil
            return False
        # Dikey kenar yoğunluğu: plaka karakterleri çok sayıda dikey kenar üretir.
        sob = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
        edges = np.abs(sob) > 60
        edge_density = float(edges.mean())
        return edge_density >= min_edge_density
    except Exception:
        # cv2 yoksa geometriye güven (mock/CI): aspect geçtiyse kabul
        return True


def refine_to_frame(
    crop: Optional[np.ndarray],
    *,
    pad_h: float = 0.08,
    pad_v: float = 0.12,
    deskew: bool = True,
) -> Optional[np.ndarray]:
    """
    ROI içindeki plakanın koyu (siyah) çerçevesini bul ve ona kırp.

    "Siyah çerçeveyi takip et": dedektör bbox'ı plakanın etrafında değişken boşluk
    bırakır; burada ROI içinde plaka-benzeri en güçlü dikdörtgen konturu bulup ona
    daraltıyoruz. Bulunamazsa girdi olduğu gibi (hafif pad'li) döner — yani asla
    bilgi kaybetmeyiz, sadece bulabildiğimizde sıkılaştırırız.

    deskew=True ise kontur belirgin biçimde eğikse minAreaRect ile düzleştirilir
    (mükemmel dikdörtgen şart değil; OCR için yeterli düzlük hedeflenir).
    """
    if crop is None or crop.size == 0:
        return None
    try:
        import cv2
    except Exception:
        return crop

    h, w = crop.shape[:2]
    if w < 20 or h < 8:
        return crop

    gray = _to_gray(crop)
    # Plaka çerçevesi/karakterleri kenar üretir; kapatma ile plaka gövdesini birleştir.
    blur = cv2.bilateralFilter(gray, 7, 50, 50)
    edges = cv2.Canny(blur, 40, 130)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(9, w // 18), 3))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    best_score = 0.0
    cx0, cy0 = w / 2.0, h / 2.0
    for c in cnts:
        rect = cv2.minAreaRect(c)
        (rcx, rcy), (rw, rh), ang = rect
        if rw < 1 or rh < 1:
            continue
        # minAreaRect genişlik/yükseklik sırası değişken → normalize et
        bw, bh = max(rw, rh), min(rw, rh)
        aspect = bw / bh
        if not (1.8 <= aspect <= 8.0):
            continue
        area_ratio = (bw * bh) / (w * h)
        if area_ratio < 0.12:                  # ROI'nin çok küçük parçası → karakter/gürültü
            continue
        # Merkeze yakın + büyük olan tercih edilir (plaka ROI'nin ortasındadır).
        dist = ((rcx - cx0) ** 2 + (rcy - cy0) ** 2) ** 0.5 / (max(w, h))
        score = area_ratio * (1.0 - min(1.0, dist))
        if score > best_score:
            best_score = score
            best = rect

    if best is None:
        return _pad(crop, pad_h, pad_v)

    (rcx, rcy), (rw, rh), ang = best
    # minAreaRect açısını [-45,45] aralığına indir (yatay plaka referansı)
    if rw < rh:
        ang += 90.0
    if ang > 45:
        ang -= 90
    elif ang < -45:
        ang += 90

    if deskew and abs(ang) > 4.0:
        # Belirgin eğim → döndürerek düzleştir, sonra eksene hizalı kırp.
        M = cv2.getRotationMatrix2D((rcx, rcy), ang, 1.0)
        rot = cv2.warpAffine(crop, M, (w, h), flags=cv2.INTER_CUBIC,
                             borderMode=cv2.BORDER_REPLICATE)
        bw, bh = (rw, rh) if rw >= rh else (rh, rw)
        out = cv2.getRectSubPix(rot, (int(round(bw)), int(round(bh))), (rcx, rcy))
        return _pad(out, pad_h, pad_v)

    # Eksene hizalı kırp (deskew gerekmiyor): bounding rect kullan.
    box = cv2.boxPoints(best)
    xs = np.clip(box[:, 0], 0, w - 1)
    ys = np.clip(box[:, 1], 0, h - 1)
    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())
    sub = crop[y1:y2, x1:x2]
    if sub.size == 0:
        return _pad(crop, pad_h, pad_v)
    return _pad(sub, pad_h, pad_v)


def _pad(crop: np.ndarray, pad_h: float, pad_v: float) -> np.ndarray:
    """Yatay/dikey oransal padding ekler (sınırları taşma olmadan)."""
    h, w = crop.shape[:2]
    px = int(w * pad_h)
    py = int(h * pad_v)
    if px <= 0 and py <= 0:
        return crop
    try:
        import cv2
        return cv2.copyMakeBorder(crop, py, py, px, px,
                                  cv2.BORDER_REPLICATE)
    except Exception:
        return crop
