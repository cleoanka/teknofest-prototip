"""Plaka düzlemsel PnP testleri (Katman 2/3).

Strateji (§8.1 sentetik kontrollü test ruhu): bilinen odak + bilinen pozdan
(derinlik Z, yaw açısı) plakanın 4 köşesini analitik olarak görüntüye izdüşür,
sonra estimate_plate_pose ile Z ve açıyı GERİ çöz. Ground-truth analitik olduğundan
formül/birim doğruluğu kamera belirsizliği olmadan kanıtlanır.

Kritik kanıt (test_pnp_beats_naive_width_on_yaw): plaka açılıyken naif genişlik-ppm
(w_px/0.52) foreshortening yüzünden yanılır; PnP ppm = focal/Z doğru kalır.
"""
import math

import numpy as np

from ai.plate_pnp import (
    estimate_plate_pose,
    default_focal_px,
    _plate_model_pts,
)
from ai.calibration import MetricSpeedEstimator
from config.settings import get_settings


PLATE_W = 0.520
PLATE_H = 0.112


def _project(focal, pp, plate_center, yaw_deg=0.0, pitch_deg=0.0,
             plate_w=PLATE_W, plate_h=PLATE_H):
    """Plaka 4 köşesini (model, metre) verilen pozdan kameraya izdüşür.

    Köşe sırası ve y-işareti plate_pnp._plate_model_pts ile birebir aynı (TL→TR→BR→BL,
    y aşağı pozitif). Dönüş: (4,2) görüntü pikselleri.
    """
    f = focal
    cx, cy = pp
    model2d = _plate_model_pts(plate_w, plate_h)          # (4,2), Z=0 düzlemi
    model3d = np.column_stack([model2d, np.zeros(4)])     # (4,3)

    cy_, sy_ = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    cp_, sp_ = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    R_yaw = np.array([[cy_, 0, sy_], [0, 1, 0], [-sy_, 0, cy_]])
    R_pitch = np.array([[1, 0, 0], [0, cp_, -sp_], [0, sp_, cp_]])
    R = R_pitch @ R_yaw
    t = np.asarray(plate_center, dtype=float)

    cam = (R @ model3d.T).T + t                           # (4,3) kamera çerçevesi
    uv = np.empty((4, 2))
    uv[:, 0] = f * cam[:, 0] / cam[:, 2] + cx
    uv[:, 1] = f * cam[:, 1] / cam[:, 2] + cy
    return uv


# ── default_focal_px ──────────────────────────────────────────────────────────

def test_default_focal_from_hfov():
    # HFOV=90° → f = (W/2)/tan(45°) = W/2
    f = default_focal_px(1920, hfov_deg=90.0)
    assert abs(f - 960.0) < 1e-6


def test_default_focal_narrower_fov_longer_focal():
    assert default_focal_px(1920, 40.0) > default_focal_px(1920, 70.0)


# ── PnP geri çözüm (frontal) ──────────────────────────────────────────────────

def test_pnp_recovers_distance_frontal():
    f, pp = 1000.0, (640.0, 360.0)
    Z = 12.0
    corners = _project(f, pp, (0.0, 0.0, Z))
    pose = estimate_plate_pose(corners, f, pp, plate_w_m=PLATE_W, plate_h_m=PLATE_H)
    assert pose is not None
    assert abs(pose.distance_m - Z) / Z < 0.02          # %2 içinde
    assert pose.yaw_deg < 1.5 and pose.pitch_deg < 1.5  # düz plaka
    assert pose.reproj_px < 0.5                          # sentetik → ~0 hata


def test_pnp_ppm_equals_focal_over_z():
    f, pp = 1200.0, (640.0, 360.0)
    Z = 8.0
    corners = _project(f, pp, (1.0, 0.0, Z))
    pose = estimate_plate_pose(corners, f, pp, plate_w_m=PLATE_W, plate_h_m=PLATE_H)
    assert pose is not None
    assert abs(pose.ppm - f / Z) / (f / Z) < 0.02


def test_pnp_recovers_yaw_angle():
    f, pp = 1000.0, (640.0, 360.0)
    corners = _project(f, pp, (0.0, 0.0, 10.0), yaw_deg=30.0)
    pose = estimate_plate_pose(corners, f, pp, plate_w_m=PLATE_W, plate_h_m=PLATE_H)
    assert pose is not None
    assert abs(pose.yaw_deg - 30.0) < 3.0


# ── KRİTİK: PnP foreshortening'i çözer, naif genişlik çözemez ──────────────────

def test_pnp_beats_naive_width_on_yaw():
    """Plaka 35° yaw'da: naif w_px/0.52 ppm'i şişirir (genişlik cos35≈0.82 kısalır);
    PnP ppm = focal/Z gerçeğe yakın kalır."""
    f, pp = 1000.0, (640.0, 360.0)
    Z = 10.0
    true_ppm = f / Z                                     # 100 px/m
    corners = _project(f, pp, (0.0, 0.0, Z), yaw_deg=35.0)

    # Naif yaklaşım: köşelerden eksen-hizalı genişlik / gerçek plaka eni
    w_px = float(corners[:, 0].max() - corners[:, 0].min())
    naive_ppm = w_px / PLATE_W

    pose = estimate_plate_pose(corners, f, pp, plate_w_m=PLATE_W, plate_h_m=PLATE_H)
    assert pose is not None

    naive_err = abs(naive_ppm - true_ppm) / true_ppm
    pnp_err = abs(pose.ppm - true_ppm) / true_ppm
    assert naive_err > 0.10                              # naif belirgin yanılır
    assert pnp_err < 0.03                                # PnP doğru
    assert pnp_err < naive_err                           # PnP kesin daha iyi


# ── Makullük geçitleri ────────────────────────────────────────────────────────

def test_pnp_rejects_wrong_corner_count():
    assert estimate_plate_pose([[0, 0], [10, 0], [10, 5]], 1000.0, (320, 240)) is None


def test_pnp_rejects_non_finite():
    bad = [[0, 0], [10, 0], [float("nan"), 5], [0, 5]]
    assert estimate_plate_pose(bad, 1000.0, (320, 240)) is None


def test_pnp_rejects_distance_out_of_range():
    f, pp = 1000.0, (640.0, 360.0)
    corners = _project(f, pp, (0.0, 0.0, 500.0))         # 500 m → üst sınır dışı
    assert estimate_plate_pose(corners, f, pp, max_distance_m=120.0) is None


def test_pnp_rejects_high_reprojection_error():
    # Köşeleri rastgele boz → hiçbir tutarlı poz yok → reproj geçidi eler
    corners = [[100, 100], [400, 110], [120, 250], [380, 90]]
    pose = estimate_plate_pose(corners, 1000.0, (640, 360), max_reproj_px=2.0)
    # Ya None (geçit eler) ya da çok yüksek değil; tutarsız geometri kabul edilmemeli
    assert pose is None or pose.reproj_px <= 2.0


# ── Füzyon: observe_plate_pose → ScaleField ───────────────────────────────────

def test_observe_plate_pose_feeds_scale_field():
    s = get_settings()
    est = MetricSpeedEstimator(s)
    f = default_focal_px(1280, s.camera_hfov_deg)
    pp = (640.0, 360.0)
    Z = 9.0
    corners = _project(f, pp, (0.0, 0.0, Z))

    used = est.observe_plate_pose(corners.tolist(), 1280, 720)
    assert used is True
    assert est.scale.n_samples == 1
    assert est.last_pose is not None
    # Eklenen ppm focal/Z'ye yakın olmalı (est kendi focal'ını HFOV'den türetir)
    assert abs(est.last_pose.distance_m - Z) / Z < 0.05


def test_observe_plate_pose_returns_false_without_corners():
    est = MetricSpeedEstimator(get_settings())
    assert est.observe_plate_pose(None, 1280, 720) is False
    assert est.scale.n_samples == 0


def test_observe_plate_pose_disabled_flag(monkeypatch):
    est = MetricSpeedEstimator(get_settings())
    monkeypatch.setattr(est.s, "plate_pnp_enabled", False, raising=False)
    f = default_focal_px(1280, 55.0)
    corners = _project(f, (640.0, 360.0), (0.0, 0.0, 9.0))
    assert est.observe_plate_pose(corners.tolist(), 1280, 720) is False
