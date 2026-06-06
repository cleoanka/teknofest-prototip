"""Statistics endpoint testleri."""
import time
import pytest
from backend.db import EventStore
from ai.schema import EventRecord


def _make_event(plate="34ABC123", risk_score=55, risk_level="MEDIUM",
                speed_kmh=70.0, vtype="car", ts=None):
    return EventRecord(
        ts=ts or time.time(),
        plate=plate,
        vtype=vtype,
        speed_kmh=speed_kmh,
        risk_score=risk_score,
        risk_level=risk_level,
        factors="phone_use",
        mode="NORMAL",
    )


def test_statistics_empty_db(client):
    r = client.get("/api/statistics")
    assert r.status_code == 200
    data = r.json()
    assert data["event_count"] == 0
    assert data["high_risk_count"] == 0
    assert data["avg_speed_kmh"] is None
    assert "risk_breakdown" in data
    assert "bandwidth_efficiency" in data
    assert "qod_trigger_count" in data


def test_statistics_counts(client):
    # Önce temizle
    client.post("/api/clear")

    # 2 MEDIUM + 1 HIGH olay ekle
    store = EventStore(":memory:")
    now = time.time()
    store.add(_make_event(risk_score=45, risk_level="MEDIUM", speed_kmh=60.0))
    store.add(_make_event(risk_score=50, risk_level="MEDIUM", speed_kmh=80.0))
    store.add(_make_event(risk_score=70, risk_level="HIGH", speed_kmh=100.0))

    stats = store.statistics(period_s=3600)
    assert stats["event_count"] == 3
    assert stats["high_risk_count"] == 1  # score >= 60
    assert stats["risk_breakdown"]["MEDIUM"] == 2
    assert stats["risk_breakdown"]["HIGH"] == 1
    assert stats["avg_speed_kmh"] == pytest.approx(80.0, abs=0.5)
    store.close()


def test_statistics_period_filter():
    store = EventStore(":memory:")
    now = time.time()
    # 2 saat önceki olay
    store.add(_make_event(ts=now - 7200))
    # şimdiki olay
    store.add(_make_event(ts=now - 10))

    stats_1h = store.statistics(period_s=3600)
    stats_3h = store.statistics(period_s=10800)

    assert stats_1h["event_count"] == 1
    assert stats_3h["event_count"] == 2
    store.close()


def test_statistics_api_returns_required_fields(client):
    r = client.get("/api/statistics")
    assert r.status_code == 200
    data = r.json()
    required = [
        "period_s", "event_count", "high_risk_count", "avg_speed_kmh",
        "risk_breakdown", "qod_trigger_count", "bandwidth_efficiency",
        "qod_mode", "bandwidth_mbps",
    ]
    for field in required:
        assert field in data, f"Eksik alan: {field}"


def test_statistics_period_param(client):
    r = client.get("/api/statistics?period_s=7200")
    assert r.status_code == 200
    assert r.json()["period_s"] == 7200.0


def test_statistics_invalid_period(client):
    r = client.get("/api/statistics?period_s=10")  # < 60 minimum
    assert r.status_code == 422
