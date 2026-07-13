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

from typing import Optional

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

    Boyut-adaptif eşikler: küçük/uzak plakalar az piksel içerdiğinden std ve kenar
    yoğunluğu doğal olarak düşer. 80px genişliğin altında eşikler kademeli gevşer,
    böylece gerçek plakalar uzakken de elenmez.
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
        # Boyut-adaptif ölçekleme: küçük/uzak plakalarda eşikleri gevşet.
        # İki referans: 80px genişlik + 35px yükseklik (karakter çözünürlüğü).
        # Her ikisi de küçükse daha serbest; büyüklerse tam eşiği kullan.
        w_scale = min(1.0, w / 80.0)
        h_scale = min(1.0, h / 35.0)
        size_scale = max(0.30, min(w_scale, h_scale))
        adj_std = min_std * size_scale
        adj_edge = min_edge_density * size_scale
        if float(gray.std()) < adj_std:
            return False
        # Dikey kenar yoğunluğu: plaka karakterleri çok sayıda dikey kenar üretir.
        sob = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
        edges = np.abs(sob) > 60
        edge_density = float(edges.mean())
        return edge_density >= adj_edge
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


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """4 noktayı TL→TR→BR→BL sırasına koy (perspektif dönüşümü için)."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]          # TL: x+y en küçük
    rect[2] = pts[np.argmax(s)]          # BR: x+y en büyük
    diff = np.diff(pts, axis=1).flatten()
    rect[1] = pts[np.argmin(diff)]       # TR: y-x en küçük
    rect[3] = pts[np.argmax(diff)]       # BL: y-x en büyük
    return rect


def perspective_correct(
    crop: Optional[np.ndarray],
    *,
    target_aspect: float = 4.64,    # TR standart plaka: 520 mm / 112 mm ≈ 4.64
    min_area_ratio: float = 0.08,   # Kontur crop alanının en az %8'i olmalı
    pad_h: float = 0.05,
    pad_v: float = 0.08,
) -> "tuple[Optional[np.ndarray], Optional[np.ndarray]]":
    """Yamuk/eğik plakayı perspektif dönüşümüyle dikdörtgene çevir.

    Neden: `refine_to_frame` sadece rotasyon yapıyor (deskew); plaka kameraya
    açılı çekildiğinde trapezoid görünür. Burada 4 köşe tespit edilip
    `getPerspectiveTransform` ile gerçek dikdörtgene düzleştirilir — OCR
    karakter çözünürlüğü ve doğruluğu önemli ölçüde artar.

    Dönüş: (düzeltilmiş_görüntü, köşeler_4x2_crop_coords).
    4 köşe bulunamazsa (None, None) döner → çağıran eski fallback'e geçer.
    Köşe sırası: TL → TR → BR → BL.
    """
    if crop is None or crop.size == 0:
        return None, None
    try:
        import cv2
    except ImportError:
        return None, None

    h, w = crop.shape[:2]
    if w < 24 or h < 8:
        return None, None

    gray = _to_gray(crop)
    # Bilateral filter + Canny: kenar korunurken gürültü azalır.
    blur = cv2.bilateralFilter(gray, 9, 75, 75)
    edges = cv2.Canny(blur, 25, 100)
    # Yatay kapama: plaka gövdesini birleştirir.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(11, w // 14), 3))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, None

    # Yeterli alana sahip konturları filtrele.
    crop_area = w * h
    valid_cnts = [c for c in cnts if cv2.contourArea(c) >= crop_area * min_area_ratio]
    if not valid_cnts:
        return None, None
    largest = max(valid_cnts, key=cv2.contourArea)

    # approxPolyDP ile 4 köşeye yaklaştır (eps kademeli artar).
    peri = cv2.arcLength(largest, True)
    corners_4 = None
    for eps in (0.02, 0.03, 0.04, 0.05, 0.06, 0.08):
        approx = cv2.approxPolyDP(largest, eps * peri, True)
        if len(approx) == 4:
            corners_4 = approx.reshape(4, 2).astype(np.float32)
            break

    if corners_4 is None:
        # 4 köşe bulunamadı → minAreaRect köşelerini kullan.
        rect = cv2.minAreaRect(largest)
        (rw, rh) = (max(rect[1]), min(rect[1]))
        if rh < 1 or rw / max(rh, 1) < 1.5:
            return None, None
        corners_4 = cv2.boxPoints(rect).astype(np.float32)

    ordered = _order_corners(corners_4)

    # Hedef dikdörtgen boyutunu hesapla (kaynak kenar uzunluklarından).
    w_top = float(np.linalg.norm(ordered[1] - ordered[0]))
    w_bot = float(np.linalg.norm(ordered[2] - ordered[3]))
    h_left = float(np.linalg.norm(ordered[3] - ordered[0]))
    h_right = float(np.linalg.norm(ordered[2] - ordered[1]))
    out_w = max(80, int(max(w_top, w_bot)))
    out_h = max(20, int(max(h_left, h_right)))

    # Aspekt oranı mantıklı mı? Plaka 1.5:1 ile 9:1 arasında olmalı.
    aspect = out_w / max(out_h, 1)
    if not (1.5 <= aspect <= 9.0):
        return None, None

    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(ordered, dst)
    warped = cv2.warpPerspective(
        crop, M, (out_w, out_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return _pad(warped, pad_h, pad_v), ordered


def refine_with_corners(
    crop: Optional[np.ndarray],
    *,
    pad_h: float = 0.05,
    pad_v: float = 0.08,
    deskew: bool = True,
) -> "tuple[Optional[np.ndarray], Optional[np.ndarray]]":
    """Plakanın perspektif düzeltmesini yap ve 4 köşeyi döndür.

    Önce tam perspektif dönüşümü dener. Sonuç orijinal crop'tan %30'dan fazla
    daha az netliyse warp reddedilir — yanlış kontur yakalandı demektir (OCR'ı
    bozar). Bu durumda köşeler de güvenilmez sayılıp None döner.

    Dönüş: (düzeltilmiş_görüntü, köşeler_4x2) veya (görüntü, None).
    Köşeler crop koordinatlarındadır; pipeline'da full-frame'e çevrilir.
    """
    if crop is None or crop.size == 0:
        return None, None

    orig_sharp = plate_sharpness(crop)
    corrected, corners = perspective_correct(crop, pad_h=pad_h, pad_v=pad_v)
    if corrected is not None:
        corr_sharp = plate_sharpness(corrected)
        # Netlik %70'in altına düştüyse warp yanlış kontur yakalamış —
        # OCR için daha kötü, köşeler de güvenilmez, fallback'e geç.
        if corr_sharp >= orig_sharp * 0.70:
            return corrected, corners

    # Fallback: rotasyon tabanlı deskew (köşe bilgisi üretilemedi)
    fallback = refine_to_frame(crop, pad_h=pad_h, pad_v=pad_v, deskew=deskew)
    return fallback, None


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
