"""Aşama 5 — metrik hız doğrulama (sentetik + çapraz-yöntem + overspeed) testleri."""
from eval.speed_eval import run_eval, mae_mape, overspeed_metrics, run_independent_gt_eval
from eval.speed_noise_probe import run_focal_bias, run_pnp_recovery


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


# ── §12-P3 — bağımsız pinhole-GT (döngüsel DEĞİL) ────────────────────────────

def test_independent_gt_pnp_depth_accurate():
    """§12-P3 — PnP+derinlik bağımsız pinhole-GT'de doğru (HFOV varsayımı doğruyken
    ~0 MAE). Üreten (pinhole) ile çözen (PnP) AYNI homografiyi paylaşmaz → döngüsel değil."""
    r = run_independent_gt_eval(speeds_kmh=(36, 72, 108), hfov_gt_deg=55.0)
    assert r["mae_pnp_depth"] < 3.0


def test_independent_gt_width_only_undershoots_longitudinal():
    """§12-P3 — yalnız-ppm (araç genişliği) yolu boyuna harekette AĞIR undershoot;
    döngüsel evalin gizlediği gerçek model-uyumsuzluğu. PnP+derinlik çok daha iyi."""
    r = run_independent_gt_eval(speeds_kmh=(72,), hfov_gt_deg=55.0)
    assert r["mae_width_only"] > 10 * r["mae_pnp_depth"] + 5.0   # ppm yolu çok daha kötü


# ── §12-P6 — focal duyarlılığı + PnP kurtarma ────────────────────────────────

def test_focal_bias_is_proportional_and_zero_at_assumption():
    """§12-P6 — derinlik-füzyonu focal-oranı kadar yanlı: HFOV=varsayım(55°)'de ~0,
    ±10°'de ~±%10 (monotonik). ppm=focal/Z'de Z∝f → dZ/dt oransal kayar."""
    rows = {hfov: (est, mape) for hfov, est, mape in run_focal_bias()}
    assert rows[55.0][1] < 1.0                       # varsayımda ~0 hata
    assert rows[45.0][0] < 72.0 < rows[65.0][0]      # dar FOV→düşük, geniş FOV→yüksek (monotonik)
    assert 5.0 < rows[45.0][1] < 35.0                # ±10° → makul ~%10-25 bias


def test_pnp_recovers_angled_plates_better_than_naive():
    """§12-P6 §D — yüksek yaw'da naif plate_ppm foreshortened plakayı reddeder; PnP kurtarır."""
    rows = {round(yaw): (naive_r, pnp_r, err) for yaw, naive_r, pnp_r, err in run_pnp_recovery()}
    # 60°'de naif plate_ppm büyük ölçüde reddeder, PnP yüksek oranda kurtarır
    assert rows[60][1] > rows[60][0] + 0.3
    # cepheden ikisi de yüksek kabul (sağlamlık kontrolü)
    assert rows[0][1] > 0.8 and rows[0][0] > 0.8
