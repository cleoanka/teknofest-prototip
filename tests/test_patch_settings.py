"""PATCH /api/settings ve /api/events/summary testleri."""
import time
import pytest
from backend.db import EventStore
from ai.schema import EventRecord


# ── PATCH /api/settings ──────────────────────────────────────────────────────

def test_patch_settings_qod_threshold(client):
    """QoD eşiği runtime'da değiştirilebilir."""
    r = client.patch("/api/settings", json={"qod_release_conf": 0.90})
    assert r.status_code == 200
    data = r.json()
    assert "qod_release_conf" in data["updated"]
    assert data["updated"]["qod_release_conf"] == pytest.approx(0.90)


def test_patch_settings_speed_limit(client):
    r = client.patch("/api/settings", json={"speed_limit_kmh": 80.0})
    assert r.status_code == 200
    assert r.json()["updated"]["speed_limit_kmh"] == 80.0


def test_patch_settings_multiple_fields(client):
    payload = {
        "qod_bbox_growth_threshold": 0.20,
        "qod_consecutive_required": 3,
        "speed_limit_kmh": 60.0,
    }
    r = client.patch("/api/settings", json=payload)
    assert r.status_code == 200
    updated = r.json()["updated"]
    assert len(updated) == 3
    assert updated["qod_bbox_growth_threshold"] == pytest.approx(0.20)
    assert updated["qod_consecutive_required"] == 3


def test_patch_settings_empty_body(client):
    r = client.patch("/api/settings", json={})
    assert r.status_code == 200
    assert r.json()["updated"] == {}


def test_patch_settings_unknown_fields_ignored(client):
    """Bilinmeyen alanlar güvenli şekilde yok sayılır (Pydantic extra='ignore')."""
    r = client.patch("/api/settings", json={"nonexistent_field": 999, "speed_limit_kmh": 50.0})
    assert r.status_code == 200
    updated = r.json()["updated"]
    assert "nonexistent_field" not in updated
    assert "speed_limit_kmh" in updated


def test_patch_settings_reflected_in_get(client):
    """PATCH sonrası GET /api/settings güncel değeri döndürür."""
    client.patch("/api/settings", json={"speed_limit_kmh": 70.0})
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert r.json()["speed"]["limit_kmh"] == 70.0


# ── /api/events/summary ──────────────────────────────────────────────────────

def test_events_summary_empty(client):
    r = client.get("/api/events/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["hours"] == 24
    assert isinstance(data["summary"], list)


def test_events_summary_custom_hours(client):
    r = client.get("/api/events/summary?hours=48")
    assert r.status_code == 200
    assert r.json()["hours"] == 48


def test_events_summary_invalid_hours(client):
    r = client.get("/api/events/summary?hours=0")
    assert r.status_code == 422
    r2 = client.get("/api/events/summary?hours=200")  # > 168
    assert r2.status_code == 422


def test_events_summary_with_data():
    """Saatlik dağılım doğru hesaplanıyor mu?"""
    store = EventStore(":memory:")
    now = time.time()
    # İki farklı saatte 3 olay ekle
    store.add(EventRecord(ts=now - 7200, plate="34A001", risk_score=40,
                          risk_level="MEDIUM", factors="", mode="NORMAL"))
    store.add(EventRecord(ts=now - 7100, plate="34A002", risk_score=50,
                          risk_level="MEDIUM", factors="", mode="NORMAL"))
    store.add(EventRecord(ts=now - 1800, plate="34A003", risk_score=70,
                          risk_level="HIGH", factors="", mode="NORMAL"))

    summary = store.hourly_summary(hours=24)
    assert len(summary) >= 1
    total = sum(s["count"] for s in summary)
    assert total == 3
    store.close()
