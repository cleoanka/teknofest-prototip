"""
Metrik hız doğrulaması — ground-truth OLMADAN nasıl güveniriz? (gercek_hiz_plani.md §8)

Üç katman:
  §8.1 Sentetik kontrollü test  : bilinen homografiyle aracı bilinen yer-hızında
        hareket ettir → beklenen km/h analitik. Hattı koştur, MAE/MAPE ölç.
        Formül + birim doğruluğunu kamera belirsizliği olmadan KANITLAR.
  §8.2 Çapraz-yöntem tutarlılığı : aynı harekette homografi (B) ve ppm(y) (A)
        bağımsız hız üretir; sapma (Bland-Altman benzeri) raporlanır.
  §8.3 Fiziksel akıl sağlığı     : hızlar yol-tipi aralığında mı, ivme fiziksel mi.
  §8.4 Overspeed kararı           : ihlal eşiğinde precision/recall.

Çıktı: `eval/speed_eval.log`. Çevrimdışı, GPU/video gerekmez (saf geometri).

Koşum:  AI_MODE=mock python -m eval.speed_eval
"""
from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple

import numpy as np

from ai.tracking import Track
from ai.homography import GroundHomography
from ai.calibration import MetricSpeedEstimator
from ai.plate_pnp import default_focal_px, _plate_model_pts
from ai.schema import BBox
from config.settings import get_settings

# Sabit sentetik sahne: görüntü trapezi ↔ yer dikdörtgeni (şerit 3.5 m, adım 12 m)
_IMG = dict(left_near=(200.0, 460.0), right_near=(520.0, 460.0),
            left_far=(300.0, 220.0), right_far=(420.0, 220.0))
_GROUND = [(0.0, 0.0), (3.5, 0.0), (0.0, 12.0), (3.5, 12.0)]


def make_scene() -> Tuple[GroundHomography, GroundHomography]:
    """(i2g, g2i): görüntü→yer ve yer→görüntü homografileri."""
    i2g = GroundHomography.from_lane_markings(
        _IMG["left_near"], _IMG["right_near"], _IMG["left_far"], _IMG["right_far"],
        lane_width_m=3.5, dash_pitch_m=12.0)
    img_pts = [_IMG["left_near"], _IMG["right_near"], _IMG["left_far"], _IMG["right_far"]]
    g2i = GroundHomography.from_correspondences(_GROUND, img_pts)
    return i2g, g2i


def _foot_track(g2i: GroundHomography, lane_x: float, z0: float,
                v_mps: float, fps: float, n: int) -> Track:
    """Yer düzleminde Z ekseninde v_mps ile ilerleyen aracın görüntü foot izini track'e yaz."""
    dt = 1.0 / fps
    t = Track(track_id=1, bbox=(0, 0, 1, 1))
    for k in range(n):
        Z = z0 + v_mps * k * dt
        px, py = g2i.to_ground(lane_x, Z)         # yer → görüntü
        t.update((px - 50, py - 10, px + 50, py), ts=k * dt)
    return t


def _foot_track_lateral(g2i: GroundHomography, z: float, x0: float,
                        v_mps: float, fps: float, n: int) -> Track:
    """Sabit derinlik Z'de YANAL (şeritler arası) hareket — Yöntem A'nın geçerli
    olduğu rejim (yanal ppm tam doğru ölçek)."""
    dt = 1.0 / fps
    t = Track(track_id=1, bbox=(0, 0, 1, 1))
    for k in range(n):
        X = x0 + v_mps * k * dt
        px, py = g2i.to_ground(X, z)
        t.update((px - 50, py - 10, px + 50, py), ts=k * dt)
    return t


def _seed_scale_field(est: MetricSpeedEstimator, g2i: GroundHomography,
                      depths: Sequence[float] = range(2, 26, 2)) -> None:
    """Bilinen genişlikte (1.8 m araç) nesneleri çeşitli derinliklerde izdüşürüp
    ppm(y) ölçek-alanını ısıt (Yöntem A için sentetik ısınma)."""
    w_m = 1.80
    for Z in depths:
        for lane_x in (0.9, 1.75, 2.6):
            pl = g2i.to_ground(lane_x - w_m / 2, float(Z))
            pr = g2i.to_ground(lane_x + w_m / 2, float(Z))
            foot = g2i.to_ground(lane_x, float(Z))
            px_w = abs(pr[0] - pl[0])
            if px_w > 1:
                est.scale.add(foot[1], px_w / w_m, weight=0.5)
    est.scale.fit()


# ── §12-P3 — BAĞIMSIZ-GT (analitik pinhole) — döngüselliği kır ───────────────
# speed_eval'in §8.1 kolu izi GroundHomography'den üretip aynı H ile çözer (MAE~0
# kaçınılmaz, yalnız cebir). Burada GT'yi tamamen bağımsız bir analitik PINHOLE
# kameradan (K[R|t]) üretir, sistemi YALNIZ sahne gözlemlerinden (plaka PnP / araç
# genişliği) oto-kalibre ettirip uçtan-uca km/h MAE ölçeriz → ilk DÜRÜST doğruluk.

_PP = (640.0, 360.0)          # asal nokta (1280×720 görüntü merkezi)
_FRAME_W, _FRAME_H = 1280, 720


def project_plate_pinhole(focal: float, center3d, yaw_deg: float = 0.0,
                          pp: Tuple[float, float] = _PP) -> np.ndarray:
    """Plaka 4 köşesini analitik pinhole ile (focal, kamera-uzayı merkezi) görüntüye
    izdüşür. GroundHomography KULLANMAZ → çözücüden bağımsız ground-truth (döngüsel değil)."""
    cx, cy = pp
    m3 = np.column_stack([_plate_model_pts(0.520, 0.112), np.zeros(4)])
    cyw, syw = np.cos(np.radians(yaw_deg)), np.sin(np.radians(yaw_deg))
    R = np.array([[cyw, 0, syw], [0, 1, 0], [-syw, 0, cyw]])
    cam = (R @ m3.T).T + np.asarray(center3d, float)
    uv = np.empty((4, 2))
    uv[:, 0] = focal * cam[:, 0] / cam[:, 2] + cx
    uv[:, 1] = focal * cam[:, 1] / cam[:, 2] + cy
    return uv


def run_independent_gt_eval(speeds_kmh: Sequence[float] = (36, 72, 108),
                            fps: float = 20.0, n: int = 8,
                            hfov_gt_deg: float = 55.0) -> Dict:
    """Analitik pinhole-GT ile uçtan-uca oto-kalibrasyon doğruluğu (boyuna hareket).

    İki kol (farklı hata kaynakları — KARIŞTIRMA):
      A — PnP+derinlik: plaka köşeleri f_gt ile üretilir, estimator HFOV varsayar
          (camera_focal_px=None). observe_plate_pose→maybe_fit→estimate. dZ/dt boyuna
          undershoot'u giderir; hfov_gt=varsayım iken MAE ~0 (oto-kalibrasyon doğru).
      B — Yalnız araç-genişliği (ppm): PnP yok → ppm(y) yer-değiştirme yolu. Boyuna
          harekette perspektif sıkışmasından undershoot → MAE büyük (döngüsel evalin
          GİZLEDİĞİ gerçek model-uyumsuzluğu)."""
    s = get_settings()
    f_assumed = default_focal_px(_FRAME_W, getattr(s, "camera_hfov_deg", 55.0))
    f_gt = default_focal_px(_FRAME_W, hfov_gt_deg)
    dt = 1.0 / fps
    z0 = 30.0                                  # uzaktan yaklaşan araç (boyuna)

    true_l, est_pnp, est_width = [], [], []
    for v in speeds_kmh:
        v_mps = v / 3.6
        # — Kol A: PnP + derinlik füzyonu —
        est_a = MetricSpeedEstimator(s.model_copy(update={"camera_focal_px": None}))
        ta = Track(track_id=1, bbox=(0, 0, 1, 1))
        for k in range(n):
            Z = z0 - v_mps * k * dt            # yaklaşıyor (Z azalır)
            uv = project_plate_pinhole(f_gt, (0.0, 1.0, Z))
            by = float(uv[:, 1].max()); cx = float((uv[:, 0].min() + uv[:, 0].max()) / 2)
            ta.update((cx - 60, by - 24, cx + 60, by), ts=k * dt)
            est_a.observe_plate_pose([list(c) for c in uv], _FRAME_W, _FRAME_H,
                                     track_id=1, ts=k * dt)
        est_a.maybe_fit()
        kmh_a, ok_a = est_a.estimate(ta)
        # — Kol B: yalnız araç genişliği (ppm yolu) —
        est_b = MetricSpeedEstimator(s.model_copy(update={"camera_focal_px": None}))
        tb = Track(track_id=1, bbox=(0, 0, 1, 1))
        veh_w_m = 1.80
        for k in range(n):
            Z = z0 - v_mps * k * dt
            half_px = f_gt * (veh_w_m / 2.0) / Z
            by = _PP[1] + f_gt * 1.2 / Z       # araç altı (yere yakın) görüntü-y
            cx = _PP[0]
            bbox = BBox(x1=cx - half_px, y1=by - 2 * half_px, x2=cx + half_px, y2=by)
            tb.update((bbox.x1, bbox.y1, bbox.x2, bbox.y2), ts=k * dt)
            est_b.observe_vehicle(bbox, "car")
        est_b.maybe_fit()
        kmh_b, ok_b = est_b.estimate(tb)

        true_l.append(float(v))
        est_pnp.append(kmh_a if (ok_a and kmh_a is not None) else float("nan"))
        est_width.append(kmh_b if (ok_b and kmh_b is not None) else float("nan"))

    mae_pnp, mape_pnp = mae_mape(true_l, est_pnp)
    mae_width, mape_width = mae_mape(true_l, est_width)
    return {
        "speeds": true_l, "fps": fps, "hfov_gt_deg": hfov_gt_deg,
        "est_pnp_depth": est_pnp, "est_width_only": est_width,
        "mae_pnp_depth": mae_pnp, "mape_pnp_depth": mape_pnp,
        "mae_width_only": mae_width, "mape_width_only": mape_width,
    }


def mae_mape(true: Sequence[float], est: Sequence[float]) -> Tuple[float, float]:
    t = np.asarray(true, float)
    e = np.asarray(est, float)
    if len(t) == 0:
        return 0.0, 0.0
    mae = float(np.mean(np.abs(e - t)))
    nz = t != 0
    mape = float(np.mean(np.abs((e[nz] - t[nz]) / t[nz])) * 100) if nz.any() else 0.0
    return mae, mape


def overspeed_metrics(true: Sequence[float], est: Sequence[float],
                      limit_kmh: float) -> Dict[str, float]:
    """İhlal kararı (hız > limit) için precision/recall/accuracy."""
    t = np.asarray(true, float) > limit_kmh
    e = np.asarray(est, float) > limit_kmh
    tp = int(np.sum(t & e)); fp = int(np.sum(~t & e))
    fn = int(np.sum(t & ~e)); tn = int(np.sum(~t & ~e))
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    acc = (tp + tn) / max(1, len(t))
    return {"precision": prec, "recall": rec, "accuracy": acc,
            "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def _estimate_series(est: MetricSpeedEstimator, g2i: GroundHomography,
                     v_true_kmh: float, fps: float = 30.0,
                     n: int = 12, lane_x: float = 1.75) -> float:
    """Sentetik aracı v_true ile koştur; son karedeki tahmini km/h döndür."""
    v_mps = v_true_kmh / 3.6
    track = _foot_track(g2i, lane_x, z0=4.0, v_mps=v_mps, fps=fps, n=n)
    kmh, calib = est.estimate(track)
    return kmh if (calib and kmh is not None) else float("nan")


def run_eval(speeds_kmh: Sequence[float] = (20, 40, 60, 90, 120),
             fps: float = 30.0, limit_kmh: float = 90.0) -> Dict:
    """Tüm doğrulama katmanlarını koştur ve sonuç sözlüğü döndür."""
    i2g, g2i = make_scene()

    true_list: List[float] = []
    est_homog: List[float] = []
    est_ppm_long: List[float] = []      # boyuna (kameraya doğru) — A'nın zayıf rejimi
    est_ppm_lat: List[float] = []       # yanal (şeritler arası) — A'nın geçerli rejimi

    for v in speeds_kmh:
        v_mps = v / 3.6
        # Yöntem B — homografi (perspektif-tam), boyuna harekette
        est_b = MetricSpeedEstimator(get_settings())
        est_b.set_homography(i2g)
        b = _estimate_series(est_b, g2i, v, fps=fps)

        # Yöntem A — ppm(y), boyuna harekette (perspektif sıkışması → düşük tahmin)
        est_a = MetricSpeedEstimator(get_settings())
        _seed_scale_field(est_a, g2i)
        a_long = _estimate_series(est_a, g2i, v, fps=fps)

        # Yöntem A — ppm(y), YANAL harekette (yanal ppm doğru ölçek → isabetli)
        est_a2 = MetricSpeedEstimator(get_settings())
        _seed_scale_field(est_a2, g2i)
        lat_track = _foot_track_lateral(g2i, z=8.0, x0=0.6, v_mps=v_mps, fps=fps, n=8)
        a_lat_kmh, a_lat_ok = est_a2.estimate(lat_track)
        a_lat = a_lat_kmh if (a_lat_ok and a_lat_kmh is not None) else float("nan")

        true_list.append(float(v))
        est_homog.append(b)
        est_ppm_long.append(a_long)
        est_ppm_lat.append(a_lat)

    mae_b, mape_b = mae_mape(true_list, est_homog)
    mae_a_long, mape_a_long = mae_mape(true_list, est_ppm_long)
    mae_a_lat, mape_a_lat = mae_mape(true_list, est_ppm_lat)
    cross = [abs(a - b) for a, b in zip(est_ppm_long, est_homog)]
    cross_mean = float(np.mean(cross)) if cross else 0.0
    os_b = overspeed_metrics(true_list, est_homog, limit_kmh)
    sane = all(0.0 <= x <= 200.0 for x in est_homog + est_ppm_lat)

    return {
        "fps": fps, "limit_kmh": limit_kmh, "speeds": list(true_list),
        "est_homography": est_homog,
        "est_ppm_long": est_ppm_long, "est_ppm_lat": est_ppm_lat,
        "mae_homography": mae_b, "mape_homography": mape_b,
        "mae_ppm_long": mae_a_long, "mape_ppm_long": mape_a_long,
        "mae_ppm_lat": mae_a_lat, "mape_ppm_lat": mape_a_lat,
        "cross_method_mean_diff": cross_mean,
        "overspeed_homography": os_b,
        "physical_sane": sane,
    }


def format_report(r: Dict) -> str:
    lines = [
        "=== Metrik Hız Doğrulama Raporu (gercek_hiz_plani.md §8) ===",
        f"FPS={r['fps']}  ihlal_limiti={r['limit_kmh']} km/h",
        "",
        "§8.1 Sentetik (perspektif-tam ground-truth):",
        f"  Gerçek (km/h)        : {[round(x,1) for x in r['speeds']]}",
        f"  Yöntem B homografi   : {[round(x,1) for x in r['est_homography']]}",
        f"  Yöntem A ppm boyuna  : {[round(x,1) for x in r['est_ppm_long']]}",
        f"  Yöntem A ppm yanal   : {[round(x,1) for x in r['est_ppm_lat']]}",
        f"  MAE (B homografi)      = {r['mae_homography']:.2f} km/h   MAPE = {r['mape_homography']:.1f}%",
        f"  MAE (A yanal rejim)    = {r['mae_ppm_lat']:.2f} km/h   MAPE = {r['mape_ppm_lat']:.1f}%",
        f"  MAE (A boyuna rejim)   = {r['mae_ppm_long']:.2f} km/h   MAPE = {r['mape_ppm_long']:.1f}%",
        "  → B perspektifi TAM çözer (MAE~0). A yalnız yanal ppm'dir: yanal harekette",
        "    isabetli, boyuna (kameraya doğru) harekette perspektif sıkışmasından düşük",
        "    tahmin eder → şerit görünürken HOMOGRAFİ tercih edilir (§7.1 füzyon önceliği).",
        "",
        f"§8.2 Çapraz-yöntem ortalama |A_boyuna - B| = {r['cross_method_mean_diff']:.2f} km/h",
        "    (büyük sapma = A boyuna rejimde bozulur → B'ye güven sinyali)",
        f"§8.3 Fiziksel akıl sağlığı (0-200 km/h) : {'GEÇTİ' if r['physical_sane'] else 'KALDI'}",
        "§8.4 Overspeed kararı (Yöntem B):",
        f"  precision={r['overspeed_homography']['precision']:.2f}  "
        f"recall={r['overspeed_homography']['recall']:.2f}  "
        f"accuracy={r['overspeed_homography']['accuracy']:.2f}",
    ]
    ig = r.get("independent_gt")
    if ig:
        lines += [
            "",
            "§12-P3 BAĞIMSIZ-GT (analitik pinhole, döngüsel DEĞİL) — boyuna hareket:",
            f"  Gerçek (km/h)        : {[round(x,1) for x in ig['speeds']]}",
            f"  PnP + derinlik (dZ/dt): {[round(x,1) for x in ig['est_pnp_depth']]}"
            f"   MAE = {ig['mae_pnp_depth']:.2f}  MAPE = {ig['mape_pnp_depth']:.1f}%",
            f"  Yalnız araç-genişliği : {[round(x,1) for x in ig['est_width_only']]}"
            f"   MAE = {ig['mae_width_only']:.2f}  MAPE = {ig['mape_width_only']:.1f}%",
            "  → PnP+derinlik bağımsız-GT'de ~0 MAE (oto-kalibrasyon DOĞRU); yalnız-ppm yolu",
            "    boyuna harekette AĞIR undershoot eder (döngüsel evalin gizlediği model-uyumsuzluğu).",
            "    (HFOV varsayımı doğruyken; HFOV yanlışsa dZ/dt focal-oranı kadar kayar — bkz. noise_probe §E.)",
        ]
    return "\n".join(lines)


def main() -> None:
    import sys
    try:                                  # Windows cp1254 konsolunda UTF-8 (→ vb.) için
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    r = run_eval()
    r["independent_gt"] = run_independent_gt_eval()      # §12-P3
    report = format_report(r)
    print(report)
    out = os.path.join(os.path.dirname(__file__), "speed_eval.log")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\n[yazıldı] {out}")
    except OSError:
        pass


if __name__ == "__main__":
    main()
