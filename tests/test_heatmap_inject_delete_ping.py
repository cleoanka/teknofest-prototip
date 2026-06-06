"""Heatmap, test event inject, single event delete ve ping testleri."""
import time
import pytest
from ai.schema import EventRecord


def _add_event(client, level="HIGH", score=70, plate="34TST0001"):
    from backend.main import state
    return state.store.add(EventRecord(
        ts=time.time(), plate=plate, risk_score=score,
        risk_level=level, factors="test", mode="NORMAL",
    ))


# ── /api/ping ─────────────────────────────────────────────────────────────────

def test_ping_200(client):
    """/api/ping endpoint'i 200 dönmeli."""
    r = client.get("/api/ping")
    assert r.status_code == 200


def test_ping_returns_pong_ts(client):
    """Yanıt pong anahtar ve sayısal zaman damgası içermeli."""
    r = client.get("/api/ping")
    data = r.json()
    assert "pong" in data
    assert isinstance(data["pong"], float)
    assert data["pong"] > 1_700_000_000  # geçerli epoch sınırı


def test_ping_has_security_headers(client):
    """/api/ping de güvenlik başlıklarını almalı."""
    r = client.get("/api/ping")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "X-Response-Time" in r.headers


# ── /api/events/heatmap ───────────────────────────────────────────────────────

def test_heatmap_200_empty(client):
    """Olay yokken 200 ve boş rows dönmeli."""
    r = client.get("/api/events/heatmap")
    assert r.status_code == 200
    data = r.json()
    assert data["rows"] == []
    assert data["total_events"] == 0


def test_heatmap_structure(client):
    """Yanıt hours, levels, rows, total_events alanlarını içermeli."""
    r = client.get("/api/events/heatmap")
    data = r.json()
    assert "hours" in data
    assert "levels" in data
    assert "rows" in data
    assert "total_events" in data
    assert set(data["levels"]) == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def test_heatmap_counts_correctly(client):
    """Eklenen olaylar doğru buckete sayılmalı."""
    from backend.main import state
    now = time.time()
    for lvl in ["HIGH", "HIGH", "MEDIUM", "CRITICAL"]:
        state.store.add(EventRecord(
            ts=now - 1800, plate="34HMP0001", risk_score=70,
            risk_level=lvl, factors="", mode="NORMAL",
        ))
    r = client.get("/api/events/heatmap?hours=24")
    assert r.status_code == 200
    data = r.json()
    assert data["total_events"] == 4
    assert len(data["rows"]) >= 1
    row = data["rows"][0]
    assert row["HIGH"] == 2
    assert row["MEDIUM"] == 1
    assert row["CRITICAL"] == 1


def test_heatmap_hours_param(client):
    """hours parametresi heatmap penceresini etkiler."""
    r = client.get("/api/events/heatmap?hours=48")
    assert r.status_code == 200
    assert r.json()["hours"] == 48


def test_heatmap_invalid_hours(client):
    """hours=0 ve hours=200 422 dönmeli."""
    assert client.get("/api/events/heatmap?hours=0").status_code == 422
    assert client.get("/api/events/heatmap?hours=200").status_code == 422


# ── POST /api/events/test ─────────────────────────────────────────────────────

def test_inject_test_events_default(client):
    """Varsayılan parametrelerle test olay enjeksiyonu çalışmalı."""
    r = client.post("/api/events/test", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["injected"] == 5
    assert len(data["ids"]) == 5
    assert data["risk_level"] == "HIGH"


def test_inject_custom_count(client):
    """count parametresi kaç olay ekleneceğini belirlemeli."""
    r = client.post("/api/events/test", json={"count": 3})
    assert r.status_code == 200
    assert r.json()["injected"] == 3


def test_inject_custom_risk_level(client):
    """risk_level parametresi eklenen olayların seviyesini belirlemeli."""
    r = client.post("/api/events/test", json={"count": 2, "risk_level": "CRITICAL"})
    assert r.status_code == 200
    data = r.json()
    assert data["risk_level"] == "CRITICAL"
    # Gerçekten eklenmiş mi?
    events = client.get("/api/events?level=CRITICAL").json()
    assert len(events) >= 2


def test_inject_count_max_100(client):
    """count > 100 olsa bile en fazla 100 olay eklenmeli."""
    r = client.post("/api/events/test", json={"count": 200})
    assert r.status_code == 200
    assert r.json()["injected"] == 100


def test_inject_updates_total_count(client):
    """Enjeksiyon sonrası total_events DB sayısını yansıtmalı."""
    r = client.post("/api/events/test", json={"count": 4})
    assert r.status_code == 200
    data = r.json()
    assert data["total_events"] >= 4


# ── DELETE /api/events/{id} ───────────────────────────────────────────────────

def test_delete_event_by_id(client):
    """Var olan olay ID ile silinebilmeli."""
    eid = _add_event(client, "MEDIUM", 40)
    r = client.delete(f"/api/events/{eid}")
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] is True
    assert data["id"] == eid


def test_delete_event_not_found(client):
    """Olmayan ID 404 dönmeli."""
    r = client.delete("/api/events/999999")
    assert r.status_code == 404


def test_delete_event_removed_from_db(client):
    """Silinen olay GET ile artık bulunamaz."""
    eid = _add_event(client, "HIGH", 70)
    client.delete(f"/api/events/{eid}")
    r = client.get(f"/api/events/{eid}")
    assert r.status_code == 404


def test_delete_event_returns_remaining(client):
    """Silme sonrası kalan olay sayısı döndürülmeli."""
    eid = _add_event(client, "MEDIUM", 40)
    r = client.delete(f"/api/events/{eid}")
    assert "remaining" in r.json()
