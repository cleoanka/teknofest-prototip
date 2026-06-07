"""
Plaka düzlemsel PnP — 4 köşeden metrik mesafe + açı + foreshortening-bağımsız ölçek.

Neden var (gercek_hiz_plani.md §4.1'in tam çözümü):
  Yöntem A.1 plaka genişliğinden ppm türetiyor: `ppm = w_piksel / 0.520`. Ama plaka
  kameraya açılı (yaw) görününce genişlik `cos(yaw)` ile DARALIR → ppm büyük çıkar →
  mesafe/hız yanlışlanır. `calibration.plate_ppm()` bunu aspect oranı sapmasıyla tespit
  edip ölçümü DÜŞÜRÜR (veri kaybı). Burada açıyı atmak yerine ÇÖZÜYORUZ:

  Plakanın 4 köşesi (plate_crop.perspective_correct çıktısı) + bilinen fiziksel boyut
  (520×112 mm) + kamera odak uzaklığı → düzlemsel PnP ile plakanın kamera-uzayı pozu
  (derinlik Z, yaw, pitch) doğrudan çözülür. Foreshortening artık bir hata değil,
  denklemin çözdüğü bir bilinmeyendir. Çıkan derinlikten foreshortening'den BAĞIMSIZ
  yerel ölçek elde edilir:  ppm = focal_px / Z.

Yöntem: Zhang (2000) düzlemsel homografi ayrıştırması. Model düzlemi Z=0'da; model→görüntü
  homografisi H = K·[r1 r2 t]. K⁻¹H sütunlarından rotasyon+öteleme geri kazanılır.

Bağımlılık: yalnız numpy (homografi DLT ile çözülür) — cv2 GEREKMEZ (K4 mock-first).
  Köşeler yoksa/geometri tutarsızsa None döner → çağıran eski ppm yoluna düşer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from ai.homography import _solve_homography

Point = Tuple[float, float]


@dataclass(frozen=True)
class PlatePose:
    """Plakanın kamera çerçevesindeki pozu (PnP çıktısı).

    distance_m : kameradan plaka merkezine derinlik (Z bileşeni, metre).
    ppm        : o derinlikteki görüntü-düzlemi ölçeği (piksel/metre) — focal/Z.
                 plate_ppm()'in foreshortening-bağımsız karşılığı; eğik plakada da doğru.
    yaw_deg    : plakanın düşey eksen etrafında kameraya göre sapması (sağa/sola dönüş).
    pitch_deg  : yatay eksen etrafında sapma (yukarı/aşağı eğim — tepe kamerası pitch'i).
    reproj_px  : model köşelerinin geri-izdüşüm RMS hatası (piksel) — güven/makullük ölçütü.
    """
    distance_m: float
    ppm: float
    yaw_deg: float
    pitch_deg: float
    reproj_px: float

    @property
    def tilt_deg(self) -> float:
        """Plaka normalinin kamera eksenine toplam açısı (yaw+pitch birleşik)."""
        return math.degrees(
            math.acos(
                max(-1.0, min(1.0,
                    math.cos(math.radians(self.yaw_deg))
                    * math.cos(math.radians(self.pitch_deg))))
            )
        )


def default_focal_px(frame_w: int, hfov_deg: float = 55.0) -> float:
    """Yatay görüş açısı (HFOV) varsayımından odak uzaklığı (piksel).

    Kalibre kamera yokken makul bir başlangıç: f = (W/2) / tan(HFOV/2).
    Tipik yol-kenarı/trafik kamerası HFOV ≈ 50–60°. Mutlak hız değil, ölçek
    TUTARLILIĞI için yeterli; gerçek focal vanishing-point'ten (ai/vanishing_point.py)
    gelirse ona override edilir.
    """
    hfov = math.radians(max(10.0, min(170.0, hfov_deg)))
    return float((frame_w / 2.0) / math.tan(hfov / 2.0))


def _plate_model_pts(plate_w_m: float, plate_h_m: float) -> np.ndarray:
    """Plaka köşelerinin model (düzlem) koordinatları, merkez orijin, metre.

    Sıra TL→TR→BR→BL — plate_crop._order_corners ile birebir aynı. Görüntü y-ekseni
    aşağı pozitif olduğundan model y de aşağı pozitif alınır (işaret tutarlılığı).
    """
    half_w, half_h = plate_w_m / 2.0, plate_h_m / 2.0
    return np.array(
        [[-half_w, -half_h],   # TL
         [+half_w, -half_h],   # TR
         [+half_w, +half_h],   # BR
         [-half_w, +half_h]],  # BL
        dtype=float,
    )


def _orthonormalize(R: np.ndarray) -> np.ndarray:
    """En yakın geçerli rotasyon matrisi (SVD polar izdüşüm); det=+1 garantisi."""
    U, _, Vt = np.linalg.svd(R)
    Rn = U @ Vt
    if np.linalg.det(Rn) < 0:          # yansıma → son sütunu çevir
        U[:, -1] *= -1
        Rn = U @ Vt
    return Rn


def estimate_plate_pose(
    corners: Optional[Sequence[Sequence[float]]],
    focal_px: float,
    principal_point: Point,
    *,
    plate_w_m: float = 0.520,
    plate_h_m: float = 0.112,
    max_reproj_px: float = 6.0,
    min_distance_m: float = 1.0,
    max_distance_m: float = 120.0,
) -> Optional[PlatePose]:
    """4 plaka köşesinden düzlemsel PnP ile plakanın kamera-uzayı pozunu çöz.

    corners: [[x,y]×4] TL→TR→BR→BL sırasında, GÖRÜNTÜ (full-frame) pikselleri.
    focal_px: kamera odak uzaklığı (piksel). principal_point: (cx, cy) görüntü merkezi.

    Dönüş: PlatePose veya None. None koşulları: köşe sayısı ≠ 4, dejenere geometri,
    Z ≤ 0 (plaka kamera arkasında), mesafe makul aralık dışı, ya da reprojeksiyon
    hatası `max_reproj_px`'i aşıyor (yanlış/gürültülü köşeler).
    """
    if corners is None:
        return None
    pts = np.asarray(corners, dtype=float)
    if pts.shape != (4, 2) or not np.all(np.isfinite(pts)):
        return None

    f = float(focal_px)
    if not np.isfinite(f) or f <= 1.0:
        return None
    cx, cy = float(principal_point[0]), float(principal_point[1])

    model = _plate_model_pts(plate_w_m, plate_h_m)

    # Model (düzlem, metre) → görüntü (piksel) homografisi. DLT 4 nokta tam çözüm.
    try:
        H = _solve_homography([tuple(m) for m in model], [tuple(p) for p in pts])
    except Exception:
        return None
    if not np.all(np.isfinite(H)):
        return None

    # K⁻¹·H = [a1 a2 a3] = λ·[r1 r2 t].  K diyagonal → ters analitik (ucuz, kararlı).
    Kinv = np.array([[1.0 / f, 0.0, -cx / f],
                     [0.0, 1.0 / f, -cy / f],
                     [0.0, 0.0, 1.0]], dtype=float)
    A = Kinv @ H
    a1, a2, a3 = A[:, 0], A[:, 1], A[:, 2]

    n1, n2 = np.linalg.norm(a1), np.linalg.norm(a2)
    if n1 < 1e-9 or n2 < 1e-9:
        return None
    # Ölçek: iki sütun normu ideal eşit; geometrik ortalama gürültüye dayanıklı.
    lam = 1.0 / math.sqrt(n1 * n2)

    r1 = a1 * lam
    r2 = a2 * lam
    t = a3 * lam
    # Plaka kameranın ÖNÜNDE olmalı (Z>0). Homografi işaret belirsizliği → düzelt.
    if t[2] < 0:
        r1, r2, t = -r1, -r2, -t
    r3 = np.cross(r1, r2)
    R = _orthonormalize(np.column_stack([r1, r2, r3]))

    Z = float(t[2])
    if not np.isfinite(Z) or not (min_distance_m <= Z <= max_distance_m):
        return None

    # Reprojeksiyon hatası: model köşelerini H ile geri yansıt, ölç (güven geçidi).
    reproj = _reprojection_rms(H, model, pts)
    if not np.isfinite(reproj) or reproj > max_reproj_px:
        return None

    # Plaka normali (model +Z) kamera çerçevesinde = R'nin 3. sütunu.
    n = R[:, 2]
    yaw = math.degrees(math.atan2(abs(n[0]), abs(n[2])))     # yatay sapma (işaretsiz)
    pitch = math.degrees(math.atan2(abs(n[1]), abs(n[2])))   # düşey sapma (işaretsiz)

    ppm = f / Z   # o derinlikteki görüntü-düzlemi ölçeği; foreshortening'den bağımsız
    return PlatePose(distance_m=Z, ppm=float(ppm),
                     yaw_deg=float(yaw), pitch_deg=float(pitch),
                     reproj_px=float(reproj))


def _reprojection_rms(H: np.ndarray, model: np.ndarray, image: np.ndarray) -> float:
    """Model köşelerini H ile yansıtıp gözlemle RMS piksel hatasını döndür."""
    homog = np.column_stack([model, np.ones(len(model))])     # (4,3)
    proj = (H @ homog.T).T                                     # (4,3)
    w = proj[:, 2]
    if np.any(np.abs(w) < 1e-12):
        return float("inf")
    uv = proj[:, :2] / w[:, None]
    d = uv - image
    return float(np.sqrt(np.mean(np.sum(d * d, axis=1))))
