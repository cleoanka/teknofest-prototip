"""Aşama 6 — kaçış noktası (VP) self-kalibrasyon + çapraz-yöntem uyum testleri."""
import numpy as np

from ai.vanishing_point import (
    vanishing_point, focal_from_orthogonal_vps, methods_agree,
    confidence_from_agreement,
)


def test_vanishing_point_recovers_common_intersection():
    P = (300.0, 200.0)
    segs = [
        (P[0], P[1], 100.0, 50.0),
        (P[0], P[1], 500.0, 100.0),
        (P[0], P[1], 350.0, 600.0),
    ]
    vp = vanishing_point(segs)
    assert vp is not None
    assert abs(vp[0] - 300.0) < 1e-3 and abs(vp[1] - 200.0) < 1e-3


def test_vanishing_point_none_for_parallel_lines():
    # Görüntüde paralel iki yatay çizgi → kaçış noktası sonsuzda → None
    segs = [(0.0, 100.0, 500.0, 100.0), (0.0, 300.0, 500.0, 300.0)]
    assert vanishing_point(segs) is None


def test_focal_recovered_from_orthogonal_vps():
    # Bilinen kamera: f=800, pp=(640,360); iki ortogonal yön → VP'ler → f geri.
    f0, pp = 800.0, (640.0, 360.0)
    d1 = np.array([2.0, 1.0, 2.0])
    d2 = np.array([1.0, 0.0, -1.0])          # d1·d2 = 0 (ortogonal)
    vp1 = (pp[0] + f0 * d1[0] / d1[2], pp[1] + f0 * d1[1] / d1[2])
    vp2 = (pp[0] + f0 * d2[0] / d2[2], pp[1] + f0 * d2[1] / d2[2])
    f = focal_from_orthogonal_vps(vp1, vp2, pp)
    assert f is not None and abs(f - 800.0) < 1e-6


def test_focal_none_for_non_orthogonal_geometry():
    # Aynı tarafta iki VP → iç çarpım pozitif → tutarsız → None
    assert focal_from_orthogonal_vps((1000.0, 360.0), (900.0, 360.0),
                                     (640.0, 360.0)) is None


def test_methods_agree_within_tolerance():
    ok, spread = methods_agree([60.0, 62.0, 58.0], rel_tol=0.10)
    assert ok and spread < 0.10


def test_methods_disagree_flags_low_confidence():
    ok, spread = methods_agree([60.0, 95.0, 30.0], rel_tol=0.10)
    assert not ok
    assert confidence_from_agreement([60.0, 95.0, 30.0]) < 0.3
    assert confidence_from_agreement([60.0, 61.0, 59.0]) > 0.8
