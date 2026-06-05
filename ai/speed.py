"""
Kalibrasyonsuz hız tahmini.

Veri setinde gecikme/kalibrasyon verisi yok (transkript). Bu yüzden ÖTR'deki
'bbox_area^exp -> PPM' yaklaşımı + max(Δmerkez, Δalan) bileşeni kullanılır;
baş-on yaklaşmada (merkez sabit, alan büyür) 0 km/h hatasını çözer.

speed_kmh = K * max(|Δalan_norm|, |Δmerkez_norm|) * fps   (K saha kalibrasyonu)
Saha kalibrasyonu (bilinen mesafe/araç boyu) ile K netleştirilir.
"""
from __future__ import annotations

from typing import Optional

from ai.tracking import Track
from config.settings import get_settings


def estimate_speed(track: Optional[Track], frame_w: int, frame_h: int,
                   fps: float, dt: float) -> Optional[float]:
    if track is None or len(track.area_history) < 2 or fps <= 0:
        return None
    s = get_settings()
    diag = (frame_w ** 2 + frame_h ** 2) ** 0.5 or 1.0

    # Alan bileşeni (yaklaşma) — alan oranının üssel dönüşümü
    a_prev = track.area_history[-2]
    a_cur = track.area_history[-1]
    frame_area = max(1.0, frame_w * frame_h)
    da = abs((a_cur - a_prev)) / frame_area
    area_component = da ** s.speed_ppm_exponent

    # Merkez bileşeni (yanal/boyuna hareket) — normalize piksel kayması
    dc = 0.0
    if len(track.center_history) >= 2:
        (px, py) = track.center_history[-2]
        (cx, cy) = track.center_history[-1]
        dc = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 / diag

    movement = max(area_component, dc)
    # Bbox jitterinden kaynaklanan gürültüyü filtrele
    if movement < 0.003:
        return None
    eff_fps = fps if dt <= 0 else (1.0 / dt)
    speed = s.speed_calibration_k * movement * (eff_fps / 30.0)
    speed = round(max(0.0, min(speed, 250.0)), 1)
    return speed if speed >= 3.0 else None
