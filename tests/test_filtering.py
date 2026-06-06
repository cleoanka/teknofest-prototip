"""Olay filtreleme parametreleri testleri."""
import time
import pytest
from backend.db import EventStore
from ai.schema import EventRecord


def _ev(ts=None, risk_score=55, risk_level="MEDIUM", vtype="car", plate="34ABC123"):
    return EventRecord(
        ts=ts or time.time(),
        plate=plate,
        vtype=vtype,
        speed_kmh=60.0,
        risk_score=risk_score,
        risk_level=risk_level,
        factors="",
        mode="NORMAL",
    )


def _store_with_data():
    store = EventStore(":memory:")
    now = time.time()
    store.add(_ev(ts=now - 7200, risk_score=40, risk_level="MEDIUM", vtype="car", plate="34AAA001"))
    store.add(_ev(ts=now - 3600, risk_score=65, risk_level="HIGH", vtype="truck", plate="06BBB002"))
    store.add(_ev(ts=now - 1800, risk_score=85, risk_level="CRITICAL", vtype="car", plate="35CCC003"))
    store.add(_ev(ts=now - 600, risk_score=30, risk_level="MEDIUM", vtype="bus", plate="07DDD004"))
    return store, now


def test_filter_min_score():
    store, _ = _store_with_data()
    result = store.list(min_score=60)
    assert len(result) == 2
    for ev in result:
        assert ev.risk_score >= 60
    store.close()


def test_filter_from_ts():
    store, now = _store_with_data()
    result = store.list(from_ts=now - 2000)
    assert len(result) == 2  # -1800 ve -600
    store.close()


def test_filter_to_ts():
    store, now = _store_with_data()
    result = store.list(to_ts=now - 2000)
    # now-7200 ve now-3600 her ikisi de < now-2000 → 2 olay
    assert len(result) == 2
    store.close()


def test_filter_from_ts_to_ts_range():
    store, now = _store_with_data()
    result = store.list(from_ts=now - 4000, to_ts=now - 1000)
    # -3600 aralıkta, -1800 aralıkta → 2 olay
    assert len(result) == 2
    store.close()


def test_filter_level():
    store, _ = _store_with_data()
    result = store.list(level="HIGH")
    assert len(result) == 1
    assert result[0].risk_level == "HIGH"
    store.close()


def test_filter_vtype():
    store, _ = _store_with_data()
    result = store.list(vtype="car")
    assert len(result) == 2
    for ev in result:
        assert ev.vtype == "car"
    store.close()


def test_filter_combined():
    store, now = _store_with_data()
    result = store.list(from_ts=now - 5000, level="MEDIUM")
    assert len(result) == 1
    assert result[0].risk_level == "MEDIUM"
    store.close()


def test_filter_invalid_level_ignored():
    store, _ = _store_with_data()
    # Geçersiz level → filtre uygulanmaz, tüm olaylar döner
    result = store.list(level="INVALID_LEVEL")
    assert len(result) == 4
    store.close()


def test_events_api_level_filter(client):
    r = client.get("/api/events?level=MEDIUM")
    assert r.status_code == 200
    data = r.json()
    for ev in data:
        assert ev["risk_level"] == "MEDIUM"


def test_events_api_vtype_filter(client):
    r = client.get("/api/events?vtype=car")
    assert r.status_code == 200


def test_events_api_limit_validation(client):
    r = client.get("/api/events?limit=1000")  # > 500 max
    assert r.status_code == 422


def test_events_api_combined_filter(client):
    r = client.get("/api/events?min_score=30&level=HIGH&limit=10")
    assert r.status_code == 200
