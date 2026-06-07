"""Metrik hız oto-kalibrasyonu testleri (Aşama 1-4: ppm, füzyon, pencere, homografi)."""
import numpy as np

from ai.schema import BBox
from ai.tracking import Track
from ai.calibration import plate_ppm, ScaleField, MetricSpeedEstimator
from ai.homography import GroundHomography
from ai.lane_detect import detect_lane_homography
from config.settings import get_settings


# ── plate_ppm ────────────────────────────────────────────────────────────────

def test_plate_ppm_correct_for_frontal_plate():
    # 52 px genişlik, ~4.33 oran (12 px yükseklik) → cepheden, güvenilir
    bb = BBox(x1=0, y1=0, x2=52, y2=12)
    ppm = plate_ppm(bb, plate_width_m=0.520)
    assert ppm is not None and abs(ppm - 100.0) < 1e-6   # 52 / 0.520


def test_plate_ppm_rejects_foreshortened_plate():
    # Oran 1.73 (52x30) — eğik görünüm, foreshortening → None
    bb = BBox(x1=0, y1=0, x2=52, y2=30)
    assert plate_ppm(bb, plate_width_m=0.520) is None


def test_plate_ppm_rejects_degenerate_box():
    assert plate_ppm(BBox(x1=0, y1=0, x2=1, y2=1)) is None


# ── ScaleField ───────────────────────────────────────────────────────────────

def test_scale_field_not_ready_before_fit():
    sf = ScaleField(min_samples=4)
    sf.add(100, 10.0)
    assert not sf.is_ready
    assert sf.ppm_at(100) is None


def test_scale_field_fits_linear_ppm_of_y():
    # ppm(y) = 0.1*y + 5 → derinlikle artan ölçek
    sf = ScaleField(min_samples=5)
    for y in (50, 100, 200, 300, 400, 500):
        sf.add(y, 0.1 * y + 5.0)
    assert sf.fit()
    assert sf.is_ready
    assert abs(sf.ppm_at(250) - (0.1 * 250 + 5.0)) < 0.5


def test_scale_field_constant_when_no_y_spread():
    sf = ScaleField(min_samples=4)
    for _ in range(6):
        sf.add(200, 12.0)        # hep aynı y → eğim güvenilmez → sabit ppm
    assert sf.fit()
    assert abs(sf.ppm_at(999) - 12.0) < 1e-6


def test_scale_field_rejects_outlier():
    sf = ScaleField(min_samples=5)
    for y in (50, 100, 200, 300, 400, 500):
        sf.add(y, 0.1 * y + 5.0)
    sf.add(250, 999.0)           # aykırı ölçüm
    sf.fit()
    # Aykırı atıldığı için tahmin hâlâ doğruya yakın
    assert abs(sf.ppm_at(250) - (0.1 * 250 + 5.0)) < 2.0


# ── MetricSpeedEstimator (sentetik metrik doğrulama) ─────────────────────────

def _track_with_foot(p0, p1, t0, t1):
    """İki yer-temas noktası ile track kur (bbox alt-orta = (cx, y2))."""
    (fx0, fy0), (fx1, fy1) = p0, p1
    t = Track(track_id=1, bbox=(fx0 - 50, fy0 - 10, fx0 + 50, fy0))
    t.update((fx0 - 50, fy0 - 10, fx0 + 50, fy0), ts=t0)
    t.update((fx1 - 50, fy1 - 10, fx1 + 50, fy1), ts=t1)
    return t


def test_metric_speed_none_before_warmup():
    est = MetricSpeedEstimator(get_settings())
    t = _track_with_foot((100, 300), (100, 320), 0.0, 0.1)
    kmh, calib = est.estimate(t)
    assert kmh is None and calib is False


def test_metric_speed_matches_known_ppm_and_dt():
    # Bilinen ppm=10 px/m sabit ölçek; foot 20 px kaydı; dt=0.1 s
    # → 2 m / 0.1 s = 20 m/s = 72.0 km/h (analitik doğru)
    est = MetricSpeedEstimator(get_settings())
    for y in (280, 300, 320, 340, 360, 380):
        est.scale.add(y, 10.0)
    est.scale.fit()
    t = _track_with_foot((100, 300), (120, 300), 0.0, 0.1)   # 20 px yatay
    kmh, calib = est.estimate(t)
    assert calib is True
    assert abs(kmh - 72.0) < 0.5


# ── Aşama 2 — araç-genişliği yedeği + füzyon ─────────────────────────────────

def test_observe_vehicle_builds_scale_from_width():
    # car tipik genişlik 1.80 m; 180 px bbox → ppm = 100
    est = MetricSpeedEstimator(get_settings())
    for y in (260, 300, 340, 380, 420, 460):
        est.observe_vehicle(BBox(x1=0, y1=y - 30, x2=180, y2=y), "car")
    est.maybe_fit()
    assert est.scale.is_ready
    assert abs(est.scale.ppm_at(360) - 100.0) < 2.0


def test_plate_outweighs_vehicle_width_in_fusion():
    # Aynı y'de çelişen ölçümler: plaka ppm=100 (w=1.0), araç ppm=50 (w=0.25).
    # Ağırlıklı ortalama plakaya yakın olmalı (basit ortalama 75'ten yüksek).
    sf = ScaleField(min_samples=3)
    sf.add(300, 100.0, weight=1.0)
    sf.add(300, 100.0, weight=1.0)
    sf.add(300, 50.0, weight=0.25)
    sf.add(300, 50.0, weight=0.25)
    sf.fit()
    assert sf.ppm_at(300) > 80.0     # plaka baskın → 90'a yakın, 75 değil


def test_metric_speed_from_vehicle_only_field():
    # Plaka yok; sadece araç genişliğinden ölçek. ppm=100 → 50px/0.1s = 18 km/h
    est = MetricSpeedEstimator(get_settings())
    for y in (260, 300, 340, 380, 420, 460):
        est.observe_vehicle(BBox(x1=0, y1=y - 30, x2=180, y2=y), "car")
    est.maybe_fit()
    t = _track_with_foot((100, 360), (150, 360), 0.0, 0.1)   # 50 px
    kmh, calib = est.estimate(t)
    assert calib is True
    assert abs(kmh - 18.0) < 1.0


# ── Aşama 3 — pencere + aykırı reddi + Kalman ────────────────────────────────

def _estimator_with_ppm(ppm=100.0, **overrides):
    s = get_settings().model_copy(update=overrides) if overrides else get_settings()
    est = MetricSpeedEstimator(s)
    for y in (260, 300, 340, 380, 420, 460):
        est.scale.add(y, ppm)
    est.scale.fit()
    return est


def _track_from_path(points, ts_list):
    t = Track(track_id=1, bbox=(points[0][0] - 50, points[0][1] - 10,
                                points[0][0] + 50, points[0][1]))
    for (x, y), ts in zip(points, ts_list):
        t.update((x - 50, y - 10, x + 50, y), ts=ts)
    return t


def test_windowed_steady_speed():
    # ppm=100; her adım 50 px / 0.1 s = 5 m/s = 18 km/h (sabit)
    est = _estimator_with_ppm(100.0)
    pts = [(x, 360) for x in (0, 50, 100, 150, 200, 250)]
    ts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    kmh, calib = est.estimate(_track_from_path(pts, ts))
    assert calib and abs(kmh - 18.0) < 1.0


def test_window_rejects_teleport_outlier():
    # Tek bir 'ışınlanma' adımı (200→600 px) fiziksel-olmayan ivme → atılır,
    # hız ~18 km/h'de kalır (pencere medyanı + ivme reddi).
    est = _estimator_with_ppm(100.0)
    pts = [(x, 360) for x in (0, 50, 100, 600, 650, 700)]
    ts = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    kmh, calib = est.estimate(_track_from_path(pts, ts))
    assert calib and abs(kmh - 18.0) < 2.0


def test_kalman_damps_sudden_change():
    # window=1 → her çağrı yalnız son adımı görür. Kalman (KalmanSpeed1D) EMA'nın
    # yerini aldı: ısındıktan (P büyük→küçük) sonra kazanç ~0.45'e oturur ve ani
    # tek-kare sıçramasını tam takip etmez — ham 54 km/h'e değil, arasına yumuşatır.
    est = _estimator_with_ppm(100.0, speed_window_frames=1)
    t = _track_from_path([(0, 360)], [0.0])
    ts = 0.1
    kmh = None
    for x in (50, 100, 150, 200, 250):          # sabit 50 px/0.1 s = 5 m/s ile ısıt
        t.update((x - 50, 350, x + 50, 360), ts=ts)
        kmh, _ = est.estimate(t)                 # her çağrı 1 Kalman güncellemesi
        ts += 0.1
    assert abs(kmh - 18.0) < 1.0                 # ısınmış, kararlı 18 km/h
    t.update((350, 350, 450, 360), ts=ts)        # foot 250→400 = 150 px/0.1 s = 15 m/s ham
    kmh2, _ = est.estimate(t)
    # kararlı kazanç (~0.45): 5 + 0.45*(15-5) ≈ 9.5 m/s ≈ 34 km/h (ham 54'ten düşük, 18'den yüksek)
    assert 18.0 < kmh2 < 54.0 and abs(kmh2 - 34.0) < 4.0


def test_prune_clears_stale_track_state():
    est = _estimator_with_ppm(100.0)
    est.estimate(_track_from_path([(0, 360), (50, 360)], [0.0, 0.1]))
    assert 1 in est._kalman
    est.prune(active_ids=set())      # track 1 artık yok
    assert 1 not in est._kalman


# ── Aşama 4 — şerit homografisi ──────────────────────────────────────────────

# Görüntü trapezi ↔ yer dikdörtgeni (şerit 3.5 m, adım 12 m)
_IMG = dict(left_near=(200.0, 400.0), right_near=(440.0, 400.0),
            left_far=(280.0, 250.0), right_far=(360.0, 250.0))
_GROUND = [(0.0, 0.0), (3.5, 0.0), (0.0, 12.0), (3.5, 12.0)]


def _i2g():
    return GroundHomography.from_lane_markings(
        _IMG["left_near"], _IMG["right_near"], _IMG["left_far"], _IMG["right_far"],
        lane_width_m=3.5, dash_pitch_m=12.0)


def _g2i():
    # Ters yön: yer → görüntü (test için araç görüntü noktalarını üretmeye yarar)
    img_pts = [_IMG["left_near"], _IMG["right_near"], _IMG["left_far"], _IMG["right_far"]]
    return GroundHomography.from_correspondences(_GROUND, img_pts)


def test_homography_maps_calibration_points_exactly():
    h = _i2g()
    for img, gnd in zip([_IMG["left_near"], _IMG["right_near"],
                         _IMG["left_far"], _IMG["right_far"]], _GROUND):
        X, Z = h.to_ground(*img)
        assert abs(X - gnd[0]) < 1e-6 and abs(Z - gnd[1]) < 1e-6


def test_homography_roundtrip_interior_point():
    i2g, g2i = _i2g(), _g2i()
    G = (1.75, 6.0)                       # şerit ortası, 6 m ileri
    px, py = g2i.to_ground(*G)            # yer → görüntü
    X, Z = i2g.to_ground(px, py)          # görüntü → yer (geri)
    assert abs(X - 1.75) < 1e-3 and abs(Z - 6.0) < 1e-3


def test_metric_speed_via_homography():
    # Araç şerit ortasında 4 m → 6 m (2 m), dt=0.1 s → 20 m/s = 72 km/h.
    i2g, g2i = _i2g(), _g2i()
    p0 = g2i.to_ground(1.75, 4.0)
    p1 = g2i.to_ground(1.75, 6.0)
    est = MetricSpeedEstimator(get_settings())
    est.set_homography(i2g)              # ölçek-alanı YOK; homografi öncelikli (§7.1)
    t = _track_from_path([p0, p1], [0.0, 0.1])
    kmh, calib = est.estimate(t)
    assert calib is True
    assert abs(kmh - 72.0) < 1.5


def test_homography_takes_priority_over_scale_field():
    # Homografi kuruluysa ölçek-alanı hazır olmasa bile metrik döner.
    est = MetricSpeedEstimator(get_settings())
    assert not est.scale.is_ready
    est.set_homography(_i2g())
    g2i = _g2i()
    t = _track_from_path([g2i.to_ground(1.75, 4.0), g2i.to_ground(1.75, 5.0)], [0.0, 0.1])
    _, calib = est.estimate(t)
    assert calib is True


# ── Problem 2 — homografi↔plaka ölçek çapraz-kontrolü (yol-tipi koruması) ─────

def test_homography_scale_conflict_guard():
    foot = (320.0, 360.0)                          # kadraj içi, geçerli homografi bölgesi
    # Tutarlı: ölçek-alanını homografinin ima ettiği ppm'le besle → çatışma YOK
    ok = MetricSpeedEstimator(get_settings())
    ok.set_homography(_i2g())
    ppm_h = ok._local_ppm_homography(*foot)
    assert ppm_h and ppm_h > 0
    for y in (300, 330, 360, 390, 420, 450):
        ok.scale.add(y, ppm_h)
    ok.scale.fit()
    assert ok._homography_scale_conflict(foot) is False

    # Çatışmalı: plaka çapası 2.5× farklı ppm diyor (homografi yol-tipini yanlış sandı)
    bad = MetricSpeedEstimator(get_settings())
    bad.set_homography(_i2g())
    for y in (300, 330, 360, 390, 420, 450):
        bad.scale.add(y, ppm_h * 2.5)
    bad.scale.fit()
    assert bad._homography_scale_conflict(foot) is True


def test_lane_detect_graceful_on_bad_input():
    # cv2 yoksa ya da girdi yetersizse çökmeden None (K4)
    assert detect_lane_homography(None) is None
    assert detect_lane_homography(np.zeros((20, 20, 3), dtype=np.uint8)) is None
    assert detect_lane_homography(np.zeros((200, 200, 3), dtype=np.uint8)) is None
