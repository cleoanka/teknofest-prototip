"""
Gürültü-altında metrik hız sağlamlık probu (GPU'suz, saf geometri).

speed_eval.py döngüseldir: izi homografi H'den üretip aynı H ile geri çözer →
MAE 0 (yalnız formül/birim doğruluğu). Bu prob, GERÇEK dünyadaki kusurları
enjekte edip "homografi (B) ve ppm-yanal (A) ne kadar dayanıklı?" sorusunu ölçer:

  1. Ayak-noktası piksel titremesi (σ px): bbox alt-orta gerçek videoda oynar;
     ufka yakın küçük ölçekte (küçük ppm) bu büyük metrik hataya çevrilir.
  2. Yanlış ölçek varsayımı: şerit gerçekte 3.5 değil 3.6 m, araç 1.8 değil 1.7 m
     ise sistematik ölçek yanlılığı (hız ona oranla kayar).

Pipeline'ın pencere medyanı + Kalman düzleştirmesi titremeyi ne kadar bastırıyor
da burada görünür (gürültülü izi tam estimator'dan geçiriyoruz).

Koşum:  AI_MODE=mock python -m eval.speed_noise_probe
"""
from __future__ import annotations

import numpy as np

from ai.tracking import Track
from ai.calibration import MetricSpeedEstimator, plate_ppm
from ai.plate_pnp import estimate_plate_pose, default_focal_px
from ai.schema import BBox
from config.settings import get_settings
from eval.speed_eval import (
    make_scene, mae_mape, _IMG,
    run_independent_gt_eval, project_plate_pinhole, _PP, _FRAME_W,
)

# Sahne görüntü köşeleri (yer dikdörtgeni ile eşlenir): near-sol, near-sağ, far-sol, far-sağ
_IMG_PTS = [_IMG["left_near"], _IMG["right_near"], _IMG["left_far"], _IMG["right_far"]]

_RNG = np.random.default_rng(20260607)
_SPEEDS = (20.0, 40.0, 60.0, 90.0, 120.0)
_FPS = 30.0
_N = 20            # §A/§B kare sayısı (araç kalibre derinlik bandında kalır)


def _foot_track_long(g2i, lane_x, z0, v_mps, fps, n, jitter_px=0.0):
    """Boyuna (kameraya doğru) ilerleyen aracın foot izini, ayak noktasına
    Gauss piksel titremesi ekleyerek üret."""
    dt = 1.0 / fps
    t = Track(track_id=1, bbox=(0, 0, 1, 1))
    for k in range(n):
        Z = z0 + v_mps * k * dt
        px, py = g2i.to_ground(lane_x, Z)             # yer → görüntü
        if jitter_px > 0:
            px += _RNG.normal(0, jitter_px)
            py += _RNG.normal(0, jitter_px)
        t.update((px - 50, py - 10, px + 50, py), ts=k * dt)
    return t


def _estimate_last(est, track):
    kmh, ok = est.estimate(track)
    return kmh if (ok and kmh is not None) else float("nan")


def run_jitter_sweep(jitters=(0.0, 0.5, 1.0, 2.0, 3.0, 5.0), trials=40):
    """Yöntem B (homografi, boyuna) — ayak titremesine karşı MAE/MAPE."""
    i2g, g2i = make_scene()
    rows = []
    for j in jitters:
        maes, mapes = [], []
        for _ in range(trials):
            true_l, est_l = [], []
            for v in _SPEEDS:
                est = MetricSpeedEstimator(get_settings())
                est.set_homography(i2g)
                tr = _foot_track_long(g2i, lane_x=1.75, z0=4.0,
                                      v_mps=v / 3.6, fps=_FPS, n=_N, jitter_px=j)
                true_l.append(v)
                est_l.append(_estimate_last(est, tr))
            mae, mape = mae_mape(true_l, est_l)
            maes.append(mae); mapes.append(mape)
        rows.append((j, float(np.mean(maes)), float(np.mean(mapes))))
    return rows


def run_scale_bias():
    """Yanlış BOYUNA ölçek (kesik-çizgi adımı) varsayımının sistematik etkisi.

    Boyuna harekette hız, dash_pitch (boyuna referans) ölçeğine bağlıdır.
    İzi gerçek adım (true_pitch) sahnesinden üretiriz; estimator hâlâ 12 m
    (otoyol) varsayar. Şehir içi yol gerçekte ~6 m adımlıdır → 12/6 = 2× şişme.
    Beklenen yanlılık: hız ≈ true·(12/true_pitch)."""
    from ai.homography import GroundHomography
    ASSUMED_PITCH = 12.0
    out = []
    for true_pitch in (12.0, 11.0, 13.0, 6.0):
        # Gerçek sahne: yer dikdörtgeni Z-uzanımı = true_pitch, aynı 4 görüntü köşesi.
        g2i_true = GroundHomography.from_correspondences(
            [(0.0, 0.0), (3.5, 0.0), (0.0, true_pitch), (3.5, true_pitch)],
            list(_IMG_PTS))
        # Estimator'ın varsayımı: adım 12 m (otoyol).
        i2g_wrong = GroundHomography.from_lane_markings(
            _IMG["left_near"], _IMG["right_near"], _IMG["left_far"], _IMG["right_far"],
            lane_width_m=3.5, dash_pitch_m=ASSUMED_PITCH)
        true_l, est_l = [], []
        for v in _SPEEDS:
            est = MetricSpeedEstimator(get_settings())
            est.set_homography(i2g_wrong)
            tr = _foot_track_long(g2i_true, lane_x=1.75, z0=2.0,
                                  v_mps=(v / 3.6), fps=_FPS, n=_N, jitter_px=0.0)
            true_l.append(v)
            est_l.append(_estimate_last(est, tr))
        mae, mape = mae_mape(true_l, est_l)
        out.append((true_pitch, mae, mape))
    return out


def _long_baseline_kmh(track, i2g, baseline):
    """Uzun-baz-çizgisi hız: Δs'yi ardışık kare yerine `baseline` kare arası al.

    Boyuna harekette kare-başı Δs küçük → jitter/Δs oranı büyük (ufukta beter).
    Daha uzun baz → Δs büyür, jitter aynı kalır → oran küçülür. Hız = toplam
    metrik yer değiştirme / toplam Δt."""
    foots = list(track.foot_history)
    tss = list(track.ts_history)
    if len(foots) <= baseline or tss[-1] is None or tss[-1 - baseline] is None:
        return float("nan")
    g0 = i2g.to_ground(*foots[-1 - baseline])
    g1 = i2g.to_ground(*foots[-1])
    if g0 is None or g1 is None:
        return float("nan")
    ds = ((g1[0] - g0[0]) ** 2 + (g1[1] - g0[1]) ** 2) ** 0.5
    dt = tss[-1] - tss[-1 - baseline]
    return ds / dt * 3.6 if dt > 0 else float("nan")


def run_mitigation_sweep(sigma=2.0, windows=(3, 5, 8), trials=60,
                         speeds=(20.0, 40.0, 60.0, 90.0)):
    """σ=2px sabit titremede iki azaltma yolunu karşılaştır:
       (1) mevcut estimator'da speed_window_frames'i büyütmek (medyan √W),
       (2) uzun-baz-çizgisi (Δs'yi W kare üzerinden ölçmek).

    Her W için izi W+3 kare uzunluğunda üretiriz: araç ölçüm anında yakın-alanda
    (büyük ppm, geçerli homografi bölgesi) kalır — uzun izle ufka kaçmaz."""
    i2g, g2i = make_scene()
    rows = []
    for W in windows:
        n = W + 3
        cur_maes, lb_maes = [], []
        for _ in range(trials):
            t_cur, e_cur, t_lb, e_lb = [], [], [], []
            for v in speeds:
                tr = _foot_track_long(g2i, lane_x=1.75, z0=4.0,
                                      v_mps=v / 3.6, fps=_FPS, n=n, jitter_px=sigma)
                est = MetricSpeedEstimator(
                    get_settings().model_copy(update={"speed_window_frames": W}))
                est.set_homography(i2g)
                t_cur.append(v); e_cur.append(_estimate_last(est, tr))
                t_lb.append(v); e_lb.append(_long_baseline_kmh(tr, i2g, W))
            cur_maes.append(mae_mape(t_cur, e_cur)[0])
            lb_maes.append(mae_mape(t_lb, e_lb)[0])
        rows.append((W, float(np.mean(cur_maes)), float(np.mean(lb_maes))))
    return rows


def run_focal_bias(hfovs=(45.0, 50.0, 55.0, 60.0, 65.0)):
    """§12-P6 — derinlik-füzyonu (dZ/dt) FOCAL duyarlılığı: ppm=focal/Z'de Z∝f
    olduğundan dZ/dt focal-oranı kadar yanlıdır (ppm YOLUNUN aksine — o focal-robust
    ama boyuna undershoot eder). GT'yi gerçek HFOV'den üret, estimator 55° varsaysın
    (camera_focal_px=None), bias'ı ölç. Beklenen: HFOV ±10° → hız ∓~%10."""
    rows = []
    for hfov in hfovs:
        r = run_independent_gt_eval(speeds_kmh=(72.0,), hfov_gt_deg=hfov)
        est = r["est_pnp_depth"][0]
        rows.append((hfov, est, r["mape_pnp_depth"]))
    return rows


def run_pnp_recovery(yaws=(0.0, 30.0, 50.0, 60.0), sigma=0.5, trials=80, Z=8.0):
    """§12-P6 §D — açılı plakada PnP KURTARMA oranı: naif plate_ppm() aspect geçidi
    (tolerans 0.35 → ancak yaw≳50°'de) eğik plakayı DÜŞÜRÜR; PnP açıyı çözüp kurtarır.
    Köşelere Gauss piksel-jitter'ı (σ) ekleyerek (üretimden bağımsız bozulma → döngüselliği
    kır) her yaw'da: (1) plate_ppm kabul oranı, (2) PnP kabul oranı, (3) PnP ppm bağıl hatası.

    DİKKAT: per-sample PnP ppm hatası küçük/uzak plakada gürültüye DUYARLIDIR (Z=8m, ~17px
    plakada σ=0.5px → ~%20). Düzlemsel PnP'nin küçük-baz derinlik belirsizliği. Bu yüzden
    PnP'nin değeri per-frame KESİNLİK değil, (a) açılı plakayı KURTARMA + (b) ScaleField'in
    aykırı-dayanıklı çok-örnekli regresyonunu beslemektir (tekil gürültü orada bastırılır)."""
    f = default_focal_px(_FRAME_W, 55.0)
    ppm_true = f / Z
    rows = []
    for yaw in yaws:
        naive_ok = pnp_ok = 0
        pnp_errs = []
        for _ in range(trials):
            uv = project_plate_pinhole(f, (0.0, 0.0, Z), yaw_deg=yaw)
            uv = uv + _RNG.normal(0, sigma, uv.shape)
            # naif plate_ppm: eksen-hizalı bbox + aspect geçidi
            xs, ys = uv[:, 0], uv[:, 1]
            bbox = BBox(x1=float(xs.min()), y1=float(ys.min()),
                        x2=float(xs.max()), y2=float(ys.max()))
            if plate_ppm(bbox) is not None:
                naive_ok += 1
            pose = estimate_plate_pose([list(c) for c in uv], f, _PP)
            if pose is not None:
                pnp_ok += 1
                pnp_errs.append(abs(pose.ppm - ppm_true) / ppm_true)
        med_err = float(np.median(pnp_errs)) * 100 if pnp_errs else float("nan")
        rows.append((yaw, naive_ok / trials, pnp_ok / trials, med_err))
    return rows


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print("=== Gürültü-altında Metrik Hız Sağlamlık Probu ===")
    print(f"Sahne: sentetik homografi, boyuna hareket, {_N} kare @ {_FPS} fps")
    print(f"Hızlar: {list(_SPEEDS)} km/h | pencere+Kalman düzleştirme AÇIK\n")

    print("§A Ayak-noktası piksel titremesi → Yöntem B (homografi):")
    print(f"  {'σ(px)':>6} | {'MAE(km/h)':>10} | {'MAPE(%)':>8}")
    for j, mae, mape in run_jitter_sweep():
        print(f"  {j:>6.1f} | {mae:>10.2f} | {mape:>8.1f}")
    print("  → titremesiz MAE~0 (döngüsel); gerçek bbox jitter'ı σ=1-3px tipiktir.\n")

    print("§B Yanlış kesik-çizgi adımı varsayımı → boyuna ölçek yanlılığı:")
    print(f"  {'gerçek_adım(m)':>16} | {'MAE(km/h)':>10} | {'MAPE(%)':>8}  (varsayım: 12 m otoyol)")
    for pitch, mae, mape in run_scale_bias():
        print(f"  {pitch:>16.2f} | {mae:>10.2f} | {mape:>8.1f}")
    print("  → adım hatası doğrudan hıza geçer; şehir içi (6 m) yolu otoyol (12 m) sanmak 2× şişirir.\n")

    print("§C Doğrulama — production estimator (mevcut) ↔ ideal uzun-baz-çizgisi:")
    print(f"  {'W(kare)':>8} | {'mevcut MAE':>11} | {'uzun-baz MAE':>13}")
    for W, cur, lb in run_mitigation_sweep():
        print(f"  {W:>8} | {cur:>11.2f} | {lb:>13.2f}")
    print("  → iki sütun ÖRTÜŞÜYOR: estimate() artık uçtan-uca uzun-baz çizgisi kullanıyor")
    print("    (eski kare-kare medyan W=8'de ~4.2 idi → yeni ~2.4, ~%40 düşük).\n")

    print("§D Açılı plaka PnP KURTARMA (§12-P6) — naif plate_ppm vs düzlemsel PnP:")
    print(f"  {'yaw(°)':>6} | {'plate_ppm kabul':>15} | {'PnP kabul':>10} | {'PnP ppm hata%':>13}")
    for yaw, naive_r, pnp_r, err in run_pnp_recovery():
        print(f"  {yaw:>6.0f} | {naive_r:>15.0%} | {pnp_r:>10.0%} | {err:>13.1f}")
    print("  → yaw≳50°'de naif plate_ppm foreshortened plakayı REDDEDER; PnP %100 kurtarır.")
    print("    Per-sample ppm hatası ~%20 (küçük plaka + jitter); ScaleField aykırı-dayanıklı")
    print("    çok-örnekli regresyonu bunu bastırır — PnP'nin değeri kesinlik değil KURTARMA.\n")

    print("§E Derinlik-füzyonu FOCAL duyarlılığı (§12-P6) — ppm=focal/Z'de Z∝f:")
    print(f"  {'HFOV_gt(°)':>10} | {'tahmin(72 gerçek)':>17} | {'MAPE(%)':>8}  (estimator 55° varsayar)")
    for hfov, est, mape in run_focal_bias():
        print(f"  {hfov:>10.0f} | {est:>17.1f} | {mape:>8.1f}")
    print("  → dZ/dt boyuna undershoot'u GİDERİR ama focal-oranı kadar yanlıdır (HFOV ±10°→∓~%10).")
    print("    ppm YOLU focal-robust ama boyuna undershoot eder; mutlak çapa: ppm→plaka 520mm, dZ/dt→focal.")
    print("    Net: derinlik füzyonu undershoot'tan (~%95) çok daha iyi; focal'ı VP'den kalibre etmek artık daha değerli.")


if __name__ == "__main__":
    main()
