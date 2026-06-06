"""
Kaçış noktası (vanishing point) ile kamera self-kalibrasyonu — bağımsız DOĞRULAMA.

Aşama 6 (gercek_hiz_plani.md §6): trafik sahnesinde iki kaçış noktası bulunur:
  • VP1 — yol yönündeki paralel çizgilerden (şerit çizgileri).
  • VP2 — araçların yanal kenarlarından (yola dik yön).
İki ortogonal VP'den kameranın odak uzaklığı (ve duruşu) geri kazanılır
(Dubská/Sochor tipi otomatik yol kamerası kalibrasyonu). Tek bilinen ölçü
(şerit genişliği / ortalama araç boyu) mutlak ölçeği sabitler.

Rol (§6): Üretimde zorunlu DEĞİL. A (plaka/araç ppm) ve B (şerit homografisi)
yöntemlerini **bağımsız bir üçüncü yöntemle çapraz doğrulamak** ve ground-truth
yokluğunda güven üretmek için. Üç yöntem birbirine yakınsa metrik hıza güveniriz.

Bağımlılık: yalnız numpy. Saf geometri — her ortamda test edilebilir.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]
Segment = Tuple[float, float, float, float]   # (x1, y1, x2, y2)


def line_through(p1: Point, p2: Point) -> np.ndarray:
    """İki noktadan geçen homojen doğru (a, b, c): a·x + b·y + c = 0."""
    return np.cross([p1[0], p1[1], 1.0], [p2[0], p2[1], 1.0])


def vanishing_point(segments: Sequence[Segment]) -> Optional[Point]:
    """Çizgi segmentlerinin ortak kesişimi (kaçış noktası) — en küçük kareler.

    Her segment bir homojen doğru verir; VP tüm doğrulara ait (l·vp=0) olduğundan
    doğru matrisinin sağ-null vektörüdür (SVD). Görüntüde paralel (VP sonsuzda)
    ise None döner.
    """
    if len(segments) < 2:
        return None
    lines = np.array([line_through((x1, y1), (x2, y2))
                      for (x1, y1, x2, y2) in segments], dtype=float)
    # Dejenere (sıfır) doğruları ele
    norms = np.linalg.norm(lines[:, :2], axis=1)
    lines = lines[norms > 1e-9]
    if len(lines) < 2:
        return None
    _, _, vt = np.linalg.svd(lines)
    h = vt[-1]
    if abs(h[2]) < 1e-9:                 # sonsuzdaki nokta (görüntüde paralel)
        return None
    return (float(h[0] / h[2]), float(h[1] / h[2]))


def focal_from_orthogonal_vps(vp1: Point, vp2: Point,
                              principal_point: Point) -> Optional[float]:
    """İki ORTOGONAL yöne ait kaçış noktasından odak uzaklığı (piksel).

    Özdeşlik: ortogonal yönlerde (vp1−pp)·(vp2−pp) = −f². Sağ taraf negatif
    değilse geometri tutarsızdır (yönler ortogonal değil) → None.
    """
    px, py = principal_point
    d = (vp1[0] - px) * (vp2[0] - px) + (vp1[1] - py) * (vp2[1] - py)
    if d >= 0:
        return None
    return float(np.sqrt(-d))


def methods_agree(values: Sequence[float], rel_tol: float = 0.10
                  ) -> Tuple[bool, float]:
    """Çapraz-yöntem uyum testi (§6/§8.2): değerler ortalamanın ±rel_tol bandında mı?

    Dönüş: (uyumlu_mu, bağıl_yayılım). Bağıl yayılım = (max−min)/ortalama; bu
    değer küçükse (≤ rel_tol) yöntemler hemfikir → metrik hıza güven yüksek.
    """
    vals = [v for v in values if v is not None and np.isfinite(v)]
    if len(vals) < 2:
        return False, float("inf")
    mean = float(np.mean(vals))
    if abs(mean) < 1e-9:
        return True, 0.0
    spread = (max(vals) - min(vals)) / abs(mean)
    return spread <= rel_tol, spread


def confidence_from_agreement(values: Sequence[float]) -> float:
    """Uyumdan 0..1 güven skoru: yayılım 0 → 1.0; yayılım ≥ %30 → 0.0."""
    ok, spread = methods_agree(values, rel_tol=1.0)
    if not np.isfinite(spread):
        return 0.0
    return float(max(0.0, min(1.0, 1.0 - spread / 0.30)))
