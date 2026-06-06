"""
Yer düzlemi homografisi — görüntü pikselini metrik kuş-bakışı koordinata eşler.

Aşama 4 (gercek_hiz_plani.md §5): yer düzlemindeki bilinen İKİ mesafe — TR şerit
genişliği (3.50 m) ve otoyol kesik çizgi adımı (12 m) — ile tam bir homografi (H)
kurulur. Bundan sonra her piksel doğrudan metrik (X, Z) yer koordinatına eşlenir;
perspektif **tam** çözülür (aracın derinliğinden bağımsız tutarlı metrik).

Bağımlılık: yalnız numpy (DLT ile çözülür) — cv2 gerekmez, her ortamda test edilebilir.
Otomatik şerit tespiti (cv2, best-effort) ayrı modüldedir: `ai/lane_detect.py`.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]


def _solve_homography(image_pts: Sequence[Point], ground_pts: Sequence[Point]) -> np.ndarray:
    """4+ nokta eşlemesinden 3x3 homografiyi DLT ile çöz (h33=1 normalizasyonu).

    Her eşleme (x,y)→(u,v) iki denklem verir:
        x·h11 + y·h12 + h13 − u·x·h31 − u·y·h32 = u
        x·h21 + y·h22 + h23 − v·x·h31 − v·y·h32 = v
    """
    A: List[List[float]] = []
    b: List[float] = []
    for (x, y), (u, v) in zip(image_pts, ground_pts):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    A_arr = np.asarray(A, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    if len(image_pts) == 4:
        h = np.linalg.solve(A_arr, b_arr)
    else:
        h, *_ = np.linalg.lstsq(A_arr, b_arr, rcond=None)
    return np.array([[h[0], h[1], h[2]],
                     [h[3], h[4], h[5]],
                     [h[6], h[7], 1.0]], dtype=float)


class GroundHomography:
    """Görüntü→yer düzlemi (metrik) perspektif dönüşümü."""

    def __init__(self, H: np.ndarray):
        self.H = np.asarray(H, dtype=float)

    @classmethod
    def from_correspondences(cls, image_pts: Sequence[Point],
                             ground_pts: Sequence[Point]) -> "GroundHomography":
        if len(image_pts) < 4 or len(image_pts) != len(ground_pts):
            raise ValueError("En az 4 ve eşit sayıda görüntü/yer noktası gerekir")
        return cls(_solve_homography(image_pts, ground_pts))

    @classmethod
    def from_lane_markings(cls, left_near: Point, right_near: Point,
                           left_far: Point, right_far: Point,
                           lane_width_m: float = 3.50,
                           dash_pitch_m: float = 12.0) -> "GroundHomography":
        """Şerit işaretlerinden homografi kur (§5.2).

        Görüntüde bir şeridin yakın/uzak kenar noktaları ↔ bilinen metrik
        dikdörtgen: yatay = şerit genişliği, dikey = kesik çizgi adımı.
        """
        image_pts = [left_near, right_near, left_far, right_far]
        ground_pts = [(0.0, 0.0), (lane_width_m, 0.0),
                      (0.0, dash_pitch_m), (lane_width_m, dash_pitch_m)]
        return cls.from_correspondences(image_pts, ground_pts)

    def to_ground(self, x: float, y: float) -> Optional[Point]:
        """Görüntü pikselini (x, y) metrik yer koordinatına (X, Z) eşle."""
        v = self.H @ np.array([float(x), float(y), 1.0])
        if abs(v[2]) < 1e-12 or not np.all(np.isfinite(v)):
            return None
        return (float(v[0] / v[2]), float(v[1] / v[2]))

    @property
    def is_valid(self) -> bool:
        return bool(np.all(np.isfinite(self.H)))
