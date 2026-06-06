"""PlateTracker — araç-id'sine bağlı plaka kararlılığı (saf mantık, cv2 gerekmez)."""
from ai.plate_tracker import PlateTracker
from ai.schema import BBox, PlateResult


def _plate(text, conf, valid=True):
    return PlateResult(text=text, confidence=conf, valid_format=valid)


def test_keeps_best_valid_reading():
    """Daha yüksek güvenli geçerli okuma öncekini ezer."""
    t = PlateTracker()
    bb = BBox(x1=0, y1=0, x2=100, y2=22)
    t.update(1, _plate("34AB123", 0.6), bb, sharpness=100, frame_id=1)
    t.update(1, _plate("34AB123", 0.9), bb, sharpness=120, frame_id=2)
    res, bbox, pw, corners = t.resolve(1)
    assert res.text == "34AB123"
    assert res.confidence == 0.9
    assert pw == 100.0


def test_empty_reading_does_not_overwrite():
    """Plaka okunamayan kare, son bilinen plakayı SİLMEZ (id'ye bağlı süreklilik)."""
    t = PlateTracker()
    bb = BBox(x1=0, y1=0, x2=100, y2=22)
    t.update(5, _plate("06XYZ99", 0.8), bb, sharpness=100, frame_id=1)
    t.update(5, PlateResult(), None, sharpness=0, frame_id=2)
    res, bbox, pw, corners = t.resolve(5)
    assert res.text == "06XYZ99"
    assert res.confidence == 0.8


def test_valid_beats_higher_conf_invalid():
    """Geçerli format, daha yüksek güvenli geçersiz okumayı yener."""
    t = PlateTracker()
    bb = BBox(x1=0, y1=0, x2=80, y2=20)
    t.update(2, _plate("ABC", 0.95, valid=False), bb, sharpness=50, frame_id=1)
    t.update(2, _plate("34AB123", 0.5, valid=True), bb, sharpness=50, frame_id=2)
    res, _, _, _ = t.resolve(2)
    assert res.text == "34AB123"
    assert res.valid_format is True


def test_resolve_unknown_track_is_empty():
    t = PlateTracker()
    res, bbox, pw, corners = t.resolve(999)
    assert res.text is None
    assert bbox is None and pw is None and corners is None


def test_none_track_id_ignored():
    t = PlateTracker()
    t.update(None, _plate("34AB123", 0.9), None, 100, 1)
    res, _, _, _ = t.resolve(None)
    assert res.text is None


def test_prune_removes_stale_tracks():
    t = PlateTracker(ttl_frames=10)
    bb = BBox(x1=0, y1=0, x2=100, y2=22)
    t.update(7, _plate("34AB123", 0.9), bb, 100, frame_id=1)
    t.prune(alive_ids=set(), frame_id=20)
    res, _, _, _ = t.resolve(7)
    assert res.text is None


def test_prune_keeps_alive_track():
    t = PlateTracker(ttl_frames=10)
    bb = BBox(x1=0, y1=0, x2=100, y2=22)
    t.update(7, _plate("34AB123", 0.9), bb, 100, frame_id=1)
    t.prune(alive_ids={7}, frame_id=100)
    res, _, _, _ = t.resolve(7)
    assert res.text == "34AB123"


def test_last_seen_bbox_returned_on_miss():
    """Plaka metni yokken bile son görülen bbox döndürülür (görselleştirme için)."""
    t = PlateTracker()
    bb = BBox(x1=10, y1=20, x2=110, y2=42)
    t.update(8, PlateResult(), bb, sharpness=0, frame_id=1)
    res, bbox, pw, corners = t.resolve(8)
    assert res.text is None
    assert bbox is not None
    assert pw is not None


def test_ema_smoothing_on_successive_bbox():
    """Ardışık bbox güncellemelerinde EMA ile konum düzgünleşir."""
    t = PlateTracker()
    bb1 = BBox(x1=0, y1=0, x2=100, y2=20)
    bb2 = BBox(x1=20, y1=10, x2=120, y2=30)
    t.update(9, _plate("06AB123", 0.8), bb1, sharpness=100, frame_id=1)
    t.update(9, _plate("06AB123", 0.85), bb2, sharpness=110, frame_id=2)
    _, bbox, _, _ = t.resolve(9)
    assert bbox is not None
    assert bb1.x1 < bbox.x1 < bb2.x2


def test_default_ttl_is_75():
    """Varsayılan TTL 75 frame (50fps'de ~1.5 sn)."""
    t = PlateTracker()
    assert t._ttl == 75


def test_corners_stored_and_retrieved():
    """4 perspektif köşesi tracker'da saklanıp döndürülür."""
    t = PlateTracker()
    bb = BBox(x1=10, y1=20, x2=110, y2=42)
    corners = [[10.0, 20.0], [110.0, 20.0], [110.0, 42.0], [10.0, 42.0]]
    t.update(10, _plate("34AB123", 0.8), bb, sharpness=80, frame_id=1, corners=corners)
    _, _, _, out_corners = t.resolve(10)
    assert out_corners is not None
    assert len(out_corners) == 4


def test_velocity_extrapolation_on_resolve():
    """Bbox hareketi varken frame_id ile extrapolasyon çalışır."""
    t = PlateTracker()
    bb1 = BBox(x1=100, y1=50, x2=200, y2=70)
    bb2 = BBox(x1=110, y1=55, x2=210, y2=75)
    t.update(11, _plate("34AB123", 0.8), bb1, sharpness=80, frame_id=10)
    t.update(11, _plate("34AB123", 0.8), bb2, sharpness=80, frame_id=11)
    # Frame 14 (3 frame sonra): velocity ile kutu taşınmalı
    _, bbox, _, _ = t.resolve(11, frame_id=14)
    assert bbox is not None
    assert bbox.cx > bb2.cx
