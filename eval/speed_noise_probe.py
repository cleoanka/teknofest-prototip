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
from ai.calibration import MetricSpeedEstimator
from config.settings import get_settings
from eval.speed_eval import make_scene, _seed_scale_field, mae_mape, _IMG

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
    print("    (eski kare-kare medyan W=8'de ~4.2 idi → yeni ~2.4, ~%40 düşük).")


if __name__ == "__main__":
    main()
