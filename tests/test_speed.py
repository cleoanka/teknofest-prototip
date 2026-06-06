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


def test_dt_last_none_without_timestamps():
    """Zaman damgası verilmemiş track'te dt_last None (geriye uyum)."""
    t = Track(track_id=1, bbox=(0, 0, 10, 10))
    t.update((0, 0, 10, 10))
    t.update((0, 0, 12, 12))
    assert t.dt_last() is None


def test_dt_last_uses_real_elapsed_time_for_dropped_frames():
    """dt_last, kare SAYISINI değil, damgalı iki örnek arası GERÇEK süreyi verir.

    Track birkaç kare 'miss' olup sonra güncellenince area_history[-2..-1] çok
    kare aralıklıdır; dt o gerçek aralığı yansıtmalı (Aşama 0).
    """
    t = Track(track_id=1, bbox=(0, 0, 10, 10))
    t.update((0, 0, 10, 10), ts=10.0)
    t.update((0, 0, 12, 12), ts=10.5)   # ~15 kare düşmüş gibi: 0.5 s geçti
    assert abs(t.dt_last() - 0.5) < 1e-9


def test_speed_scales_with_track_video_timeline_dt():
    """Aynı piksel hareketi, yarı sürede → ~2x hız. Track Δt'si kullanılır,
    çağıranın dt'si DEĞİL (her ikisinde de dt=0.033 geçiliyor)."""
    fast = Track(track_id=1, bbox=(100, 100, 200, 200))
    fast.update((100, 100, 200, 200), ts=0.0)
    fast.update((90, 110, 230, 260), ts=0.1)    # dt = 0.1 s

    slow = Track(track_id=2, bbox=(100, 100, 200, 200))
    slow.update((100, 100, 200, 200), ts=0.0)
    slow.update((90, 110, 230, 260), ts=0.2)    # aynı hareket, dt = 0.2 s

    sp_fast = estimate_speed(fast, 640, 360, 30, 0.033)
    sp_slow = estimate_speed(slow, 640, 360, 30, 0.033)
    assert sp_fast is not None and sp_slow is not None
    assert abs(sp_fast - 2 * sp_slow) < 0.5   # yarı süre → iki kat hız


def test_tracker_assigns_stable_ids():
    tr = IOUTracker()
    ids1 = tr.update([(100, 100, 200, 200)])
    ids2 = tr.update([(105, 102, 205, 203)])   # aynı araç, hafif kaymış
    assert ids1 == ids2                         # track_id korunur
    growth = tr.get(ids1[0]).area_growth_ratio()
    assert isinstance(growth, float)
