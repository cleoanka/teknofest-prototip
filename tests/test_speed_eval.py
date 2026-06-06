"""Aşama 5 — metrik hız doğrulama (sentetik + çapraz-yöntem + overspeed) testleri."""
from eval.speed_eval import run_eval, mae_mape, overspeed_metrics


def test_mae_mape_hand_example():
    mae, mape = mae_mape([100.0, 50.0], [110.0, 45.0])
    assert abs(mae - 7.5) < 1e-9                 # (10 + 5)/2
    assert abs(mape - 10.0) < 1e-9               # (10% + 10%)/2


def test_overspeed_metrics_hand_example():
    true = [40, 60, 100, 120]
    est = [45, 55, 105, 80]                      # limit 90: gerçek ihlal {100,120}, tahmin {105}
    m = overspeed_metrics(true, est, limit_kmh=90.0)
    assert m["tp"] == 1 and m["fn"] == 1 and m["fp"] == 0 and m["tn"] == 2
    assert m["precision"] == 1.0
    assert abs(m["recall"] - 0.5) < 1e-9


def test_synthetic_homography_is_exact():
    """§8.1 — homografi perspektifi tam çözer: MAE ~0 (formül+birim kanıtı)."""
    r = run_eval(speeds_kmh=(30, 60, 90, 120))
    assert r["mae_homography"] < 0.5
    assert r["physical_sane"] is True


def test_ppm_accurate_in_lateral_regime():
    """§8.1 — ppm(y) yanal harekette doğru ölçek (A'nın geçerli rejimi): MAE ~0."""
    r = run_eval(speeds_kmh=(30, 60, 90))
    assert r["mae_ppm_lat"] < 1.0


def test_ppm_underestimates_longitudinal():
    """ppm boyuna harekette perspektif sıkışmasından düşük tahmin eder
    (homografinin neden gerekli olduğunun kanıtı)."""
    r = run_eval(speeds_kmh=(60, 90, 120))
    assert r["mae_ppm_long"] > r["mae_ppm_lat"]      # boyuna belirgin daha kötü


def test_overspeed_decision_reliable_with_homography():
    """§8.4 — homografi ile ihlal kararı yüksek isabet."""
    r = run_eval(speeds_kmh=(20, 40, 60, 90, 120), limit_kmh=90.0)
    os = r["overspeed_homography"]
    assert os["precision"] == 1.0 and os["recall"] == 1.0
