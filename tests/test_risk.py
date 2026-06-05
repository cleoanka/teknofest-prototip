from ai.risk import assess_risk
from ai.schema import DriverState


def test_low_risk_clean_driver():
    r = assess_risk(DriverState(), speed_kmh=40)
    assert r.score == 0 and r.level == "LOW" and r.factors == []


def test_phone_use_weight():
    r = assess_risk(DriverState(phone_use=True), speed_kmh=None)
    assert r.score == 40 and r.level == "MEDIUM"
    assert "telefon_kullanimi" in r.factors


def test_multiple_factors_accumulate():
    r = assess_risk(DriverState(phone_use=True, fatigue=True, smoking=True), speed_kmh=80)
    # 40 + 30 + 20 + 15(overspeed) = 105 -> 100 cap
    assert r.score == 100 and r.level == "CRITICAL"
    assert set(["telefon_kullanimi", "yorgunluk", "sigara", "hiz_asimi"]).issubset(set(r.factors))


def test_overspeed_only_above_limit():
    r_under = assess_risk(DriverState(), speed_kmh=49)
    r_over = assess_risk(DriverState(), speed_kmh=60)
    assert "hiz_asimi" not in r_under.factors
    assert "hiz_asimi" in r_over.factors
