"""
Otomatik şerit tespitinden yer düzlemi homografisi (Aşama 4, §5.2) — BEST-EFFORT.

Bu modül, net şerit çizgileri görünürken görüntüden 4 nokta çıkarıp
`GroundHomography` kurar. Gerçek koşullarda şerit tespiti gürültülüdür
(gece/yağmur/aşınmış çizgi) → güven düşükse **None** döner ve sistem
ppm(y) ölçek-alanına (Aşama 1-2) düşer (§7.1 füzyon önceliği, K4 nazik düşüş).

Bağımlılık: OpenCV (cv2). Kurulu değilse import-korumalı: fonksiyon None döndürür,
sistem çökmez. Doğruluğu gerçek videoyla doğrulanır; birim testleri yalnızca
"çökme yok / yetersiz girdide None" sözleşmesini kontrol eder.

ÖNEMLİ: Bu yol varsayılan KAPALIdır (`settings.homography_auto=False`). Güvenilir
metrik için tercih edilen yol, bilinen 4 şerit noktasıyla manuel
`GroundHomography.from_lane_markings(...)` (perspektif-tam, deterministik).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from ai.homography import GroundHomography

try:                                  # cv2 opsiyonel — yoksa otomatik yol devre dışı
    import cv2  # type: ignore
    _HAS_CV2 = True
except Exception:                     # pragma: no cover - ortam bağımlı
    _HAS_CV2 = False

Line = Tuple[float, float]            # (slope m, intercept b) :  x = m*y + b


def _line_x_at(line: Line, y: float) -> float:
    m, b = line
    return m * y + b


def _fit_side(segments: List[Tuple[float, float, float, float]]) -> Optional[Line]:
    """Segmentlerden x = m*y + b temsil doğrusu (y'ye göre fit; dik çizgiler güvenli)."""
    if len(segments) < 2:
        return None
    ys: List[float] = []
    xs: List[float] = []
    for x1, y1, x2, y2 in segments:
        ys += [y1, y2]
        xs += [x1, x2]
    ys_a = np.asarray(ys, dtype=float)
    xs_a = np.asarray(xs, dtype=float)
    if float(np.std(ys_a)) < 1e-3:
        return None
    m, b = np.polyfit(ys_a, xs_a, 1)
    return (float(m), float(b))


def detect_lane_homography(frame: np.ndarray,
                           lane_width_m: float = 3.50,
                           dash_pitch_m: float = 12.0,
                           roi_top_ratio: float = 0.55) -> Optional[GroundHomography]:
    """Kareden sol/sağ şerit çizgilerini bulup homografi kur. Güven düşükse None.

    Yöntem: alt trapez ROI → Canny → HoughLinesP → eğim işaretine göre sol/sağ
    ayır → her tarafa temsil doğrusu → iki y seviyesinde (yakın/uzak) dört nokta.
    Dikey ROI aralığı bir kesik-çizgi adımı (`dash_pitch_m`) varsayımıyla boyuna
    ölçeği verir; yatay şerit genişliği yanal ölçeği. (Bu boyuna varsayım kabadır;
    kesin boyuna ölçek Aşama 6 VP yöntemiyle iyileştirilir.)
    """
    if not _HAS_CV2 or frame is None or getattr(frame, "size", 0) == 0:
        return None
    if frame.ndim != 3:
        return None
    h, w = frame.shape[:2]
    if h < 40 or w < 40:
        return None

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 180)

    # Alt trapez ROI maskesi (yol bölgesi) — gökyüzü/kenar gürültüsünü ele
    y_top = int(h * roi_top_ratio)
    mask = np.zeros_like(edges)
    poly = np.array([[(int(0.05 * w), h), (int(0.45 * w), y_top),
                      (int(0.55 * w), y_top), (int(0.95 * w), h)]], dtype=np.int32)
    cv2.fillPoly(mask, poly, 255)
    edges = cv2.bitwise_and(edges, mask)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=40,
                            minLineLength=int(0.15 * h), maxLineGap=40)
    if lines is None:
        return None

    left: List[Tuple[float, float, float, float]] = []
    right: List[Tuple[float, float, float, float]] = []
    for ln in lines:
        x1, y1, x2, y2 = (float(v) for v in ln[0])
        if abs(y2 - y1) < 1e-3:
            continue
        slope = (x2 - x1) / (y2 - y1)      # dx/dy
        if abs(slope) > 4.0:               # neredeyse yatay → şerit değil
            continue
        (left if slope < 0 else right).append((x1, y1, x2, y2))

    ll = _fit_side(left)
    rl = _fit_side(right)
    if ll is None or rl is None:
        return None

    y_near = float(h - 1)
    y_far = float(y_top)
    left_near = (_line_x_at(ll, y_near), y_near)
    right_near = (_line_x_at(rl, y_near), y_near)
    left_far = (_line_x_at(ll, y_far), y_far)
    right_far = (_line_x_at(rl, y_far), y_far)

    # Akıl sağlığı: yakında sol < sağ ve makul genişlik; çizgiler çakışmasın
    if not (left_near[0] < right_near[0] and left_far[0] < right_far[0]):
        return None
    if (right_near[0] - left_near[0]) < 0.02 * w:
        return None

    try:
        H = GroundHomography.from_lane_markings(
            left_near, right_near, left_far, right_far,
            lane_width_m=lane_width_m, dash_pitch_m=dash_pitch_m)
    except Exception:                      # pragma: no cover - dejenere geometri
        return None
    return H if H.is_valid else None
