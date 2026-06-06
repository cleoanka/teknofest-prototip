"""plate_crop — plaka-benzerlik geçidi + siyah çerçeve takip crop'u.

cv2 yoksa testler graceful-degrade'i doğrular (K4). cv2 varsa gerçek sinyalleri test eder.
"""
import numpy as np
import pytest

from ai.plate_crop import looks_like_plate, refine_to_frame, plate_sharpness

cv2 = pytest.importorskip("cv2")


def _synthetic_plate(w=200, h=44):
    """Beyaz zemin + siyah karakter çubukları (plaka imzası: dikey kenarlar)."""
    img = np.full((h, w, 3), 235, dtype=np.uint8)
    for i, x in enumerate(range(15, w - 15, 24)):
        img[10:h - 10, x:x + 10] = 20      # koyu "karakter"
    return img


def _uniform_wall(w=200, h=44):
    return np.full((h, w, 3), 150, dtype=np.uint8)


def test_real_plate_passes_gate():
    assert looks_like_plate(_synthetic_plate()) is True


def test_uniform_region_rejected():
    """Düz duvar/panel plaka değildir (düşük kontrast + kenar yok)."""
    assert looks_like_plate(_uniform_wall()) is False


def test_wrong_aspect_rejected():
    """Kare bir bölge plaka oranında değil → reddedilir."""
    sq = _synthetic_plate(w=50, h=50)
    assert looks_like_plate(sq) is False


def test_too_small_rejected():
    assert looks_like_plate(_synthetic_plate(w=20, h=6)) is False


def test_none_and_empty_rejected():
    assert looks_like_plate(None) is False
    assert looks_like_plate(np.zeros((0, 0, 3), dtype=np.uint8)) is False


def test_refine_returns_image():
    out = refine_to_frame(_synthetic_plate())
    assert out is not None and out.size > 0
    assert out.ndim == 3


def test_refine_handles_none():
    assert refine_to_frame(None) is None


def test_sharpness_orders_blur():
    sharp = _synthetic_plate()
    blur = cv2.GaussianBlur(sharp, (9, 9), 0)
    assert plate_sharpness(sharp) > plate_sharpness(blur)
