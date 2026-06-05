from ai.tracking import Track, IOUTracker
from ai.speed import estimate_speed


def test_speed_none_for_empty_track():
    assert estimate_speed(None, 640, 360, 30, 0.033) is None
    t = Track(track_id=1, bbox=(0, 0, 10, 10))
    t.update((0, 0, 10, 10))  # tek ölçüm
    assert estimate_speed(t, 640, 360, 30, 0.033) is None


def test_speed_positive_when_approaching():
    t = Track(track_id=1, bbox=(100, 100, 200, 200))
    t.update((100, 100, 200, 200))
    t.update((90, 110, 230, 260))   # büyüdü + merkez kaydı (yaklaşma)
    sp = estimate_speed(t, 640, 360, 30, 0.033)
    assert sp is not None and sp > 0


def test_speed_capped():
    t = Track(track_id=1, bbox=(0, 0, 5, 5))
    t.update((0, 0, 5, 5))
    t.update((0, 0, 640, 360))      # aşırı büyüme
    sp = estimate_speed(t, 640, 360, 30, 0.033)
    assert sp is not None and sp <= 250.0


def test_tracker_assigns_stable_ids():
    tr = IOUTracker()
    ids1 = tr.update([(100, 100, 200, 200)])
    ids2 = tr.update([(105, 102, 205, 203)])   # aynı araç, hafif kaymış
    assert ids1 == ids2                         # track_id korunur
    growth = tr.get(ids1[0]).area_growth_ratio()
    assert isinstance(growth, float)
