from ai.qod_trigger import QoDTriggerEngine, TriggerContext
from config.settings import Settings


def make_engine():
    return QoDTriggerEngine(Settings())


def approaching_ctx():
    # Koşul A (yaklaşma) + D (ROI içinde) pozitif
    return TriggerContext(bbox_growth=0.30, vehicle_present=True,
                          vehicle_conf=0.5, vehicle_norm_y2=0.6)


def test_no_trigger_without_conditions():
    eng = make_engine()
    ctx = TriggerContext(vehicle_present=True, vehicle_conf=0.9,
                         vehicle_norm_y2=0.2, bbox_growth=0.0)
    d = eng.evaluate(ctx)
    assert d.should_be_critical is False
    assert eng.is_critical is False


def test_requires_two_consecutive_positives():
    eng = make_engine()
    d1 = eng.evaluate(approaching_ctx())
    assert eng.is_critical is False          # ilk pozitif: henüz değil
    assert d1.fired_this_cycle is False
    d2 = eng.evaluate(approaching_ctx())
    assert eng.is_critical is True           # ikinci ardışık: tetiklendi
    assert d2.fired_this_cycle is True
    assert any(r.startswith("A") for r in d2.reasons)


def test_single_positive_then_negative_resets():
    eng = make_engine()
    eng.evaluate(approaching_ctx())          # 1. pozitif
    eng.evaluate(TriggerContext(vehicle_present=True, vehicle_conf=0.9,
                                vehicle_norm_y2=0.2))   # negatif -> reset
    assert eng.is_critical is False


def test_condition_B_low_confidence():
    eng = make_engine()
    ctx = TriggerContext(vehicle_present=True, vehicle_conf=0.40, vehicle_norm_y2=0.2)
    eng.evaluate(ctx); eng.evaluate(ctx)
    assert eng.is_critical is True


def test_condition_C_plate_unreadable():
    eng = make_engine()
    ctx = TriggerContext(vehicle_present=True, vehicle_conf=0.9, vehicle_norm_y2=0.2,
                         plate_roi_present=True, plate_ocr_conf=0.5)
    eng.evaluate(ctx); eng.evaluate(ctx)
    assert eng.is_critical is True


def test_release_on_high_confidence():
    eng = make_engine()
    eng.evaluate(approaching_ctx()); eng.evaluate(approaching_ctx())
    assert eng.is_critical is True
    good = TriggerContext(vehicle_present=True, vehicle_conf=0.95,
                          vehicle_norm_y2=0.6, plate_roi_present=True, plate_ocr_conf=0.95)
    d = eng.evaluate(good, dt_s=0.5)
    assert eng.is_critical is False
    assert d.released_this_cycle is True


def test_release_on_timeout():
    eng = make_engine()
    eng.evaluate(approaching_ctx()); eng.evaluate(approaching_ctx())
    assert eng.is_critical is True
    # süre dolumu: tek seferde max_session aşımı
    stay = TriggerContext(vehicle_present=True, vehicle_conf=0.6,
                          vehicle_norm_y2=0.6, plate_ocr_conf=0.5)
    d = eng.evaluate(stay, dt_s=6.0)
    assert eng.is_critical is False
    assert "release:timeout" in d.reasons


def test_release_on_out_of_roi():
    eng = make_engine()
    eng.evaluate(approaching_ctx()); eng.evaluate(approaching_ctx())
    assert eng.is_critical is True
    gone = TriggerContext(vehicle_present=False)
    d = eng.evaluate(gone, dt_s=0.5)
    assert eng.is_critical is False
    assert "release:roi_disi" in d.reasons
