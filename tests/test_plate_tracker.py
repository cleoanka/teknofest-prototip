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
    res, bbox, pw = t.resolve(1)
    assert res.text == "34AB123"
    assert res.confidence == 0.9
    assert pw == 100.0


def test_empty_reading_does_not_overwrite():
    """Plaka okunamayan kare, son bilinen plakayı SİLMEZ (id'ye bağlı süreklilik)."""
    t = PlateTracker()
    bb = BBox(x1=0, y1=0, x2=100, y2=22)
    t.update(5, _plate("06XYZ99", 0.8), bb, sharpness=100, frame_id=1)
    t.update(5, PlateResult(), None, sharpness=0, frame_id=2)   # boş okuma
    res, bbox, pw = t.resolve(5)
    assert res.text == "06XYZ99"
    assert res.confidence == 0.8


def test_valid_beats_higher_conf_invalid():
    """Geçerli format, daha yüksek güvenli geçersiz okumayı yener."""
    t = PlateTracker()
    bb = BBox(x1=0, y1=0, x2=80, y2=20)
    t.update(2, _plate("ABC", 0.95, valid=False), bb, sharpness=50, frame_id=1)
    t.update(2, _plate("34AB123", 0.5, valid=True), bb, sharpness=50, frame_id=2)
    res, _, _ = t.resolve(2)
    assert res.text == "34AB123"
    assert res.valid_format is True


def test_resolve_unknown_track_is_empty():
    t = PlateTracker()
    res, bbox, pw = t.resolve(999)
    assert res.text is None
    assert bbox is None and pw is None


def test_none_track_id_ignored():
    t = PlateTracker()
    t.update(None, _plate("34AB123", 0.9), None, 100, 1)
    res, _, _ = t.resolve(None)
    assert res.text is None


def test_prune_removes_stale_tracks():
    t = PlateTracker(ttl_frames=10)
    bb = BBox(x1=0, y1=0, x2=100, y2=22)
    t.update(7, _plate("34AB123", 0.9), bb, 100, frame_id=1)
    # Araç artık sahnede değil ve ttl aşıldı → silinmeli
    t.prune(alive_ids=set(), frame_id=20)
    res, _, _ = t.resolve(7)
    assert res.text is None


def test_prune_keeps_alive_track():
    t = PlateTracker(ttl_frames=10)
    bb = BBox(x1=0, y1=0, x2=100, y2=22)
    t.update(7, _plate("34AB123", 0.9), bb, 100, frame_id=1)
    t.prune(alive_ids={7}, frame_id=100)   # hâlâ canlı → korunur
    res, _, _ = t.resolve(7)
    assert res.text == "34AB123"
