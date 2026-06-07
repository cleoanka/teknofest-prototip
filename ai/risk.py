"""
Risk skor motoru — sürücü davranışlarını tek bir 0-100 risk skoruna indirger.

Şartname madde 4.4: "yol güvenliğini tehdit edebilecek sürücü davranışları".
Ağırlıklar config.settings.RISK_WEIGHTS içinde, tek noktadan ayarlanır.
"""
from __future__ import annotations

from typing import Optional

from ai.schema import DriverState, RiskAssessment
from config.settings import get_settings, RISK_WEIGHTS, RISK_LEVELS


def _level(score: int) -> str:
    label = "LOW"
    for threshold, name in RISK_LEVELS:
        if score >= threshold:
            label = name
    return label


def assess_risk(driver: DriverState, speed_kmh: Optional[float],
                zigzag: bool = False, vtype: Optional[str] = None,
                harsh_braking: bool = False) -> RiskAssessment:
    s = get_settings()
    score = 0
    factors = []

    if driver.phone_use:
        score += RISK_WEIGHTS["phone_use"]; factors.append("telefon_kullanimi")
    if driver.fatigue:
        score += RISK_WEIGHTS["fatigue"]; factors.append("yorgunluk")
    if driver.smoking:
        score += RISK_WEIGHTS["smoking"]; factors.append("sigara")
    if driver.no_seatbelt:
        score += RISK_WEIGHTS["no_seatbelt"]; factors.append("emniyet_kemeri_yok")
    if driver.headphone:
        score += RISK_WEIGHTS["headphone"]; factors.append("kulaklik")
    # Araç tipine göre dinamik limit (otomobil/otobüs/kamyon farklı sınırlara tabidir);
    # haritada karşılığı yoksa genel speed_limit_kmh'a düşülür.
    limit = s.speed_limit_by_vtype.get(vtype, s.speed_limit_kmh) if vtype else s.speed_limit_kmh
    if speed_kmh is not None and speed_kmh > limit:
        score += RISK_WEIGHTS["overspeed"]; factors.append("hiz_asimi")
    if zigzag:
        score += RISK_WEIGHTS["zigzag"]; factors.append("zigzag")
    if harsh_braking:
        score += RISK_WEIGHTS["harsh_braking"]; factors.append("ani_fren")

    score = int(min(score, 100))
    return RiskAssessment(score=score, level=_level(score), factors=factors)
