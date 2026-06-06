"""Yeni endpoint testleri — vehicles/{plate}, events/{id}, export, qod/sessions."""
import time
import pytest
from backend.db import EventStore
from ai.schema import EventRecord


def _seed_event(store: EventStore, plate="34ABC123", risk_score=55,
                risk_level="MEDIUM", vtype="car") -> int:
    return store.add(EventRecord(
        ts=time.time(),
        plate=plate,
        vtype=vtype,
        speed_kmh=70.0,
        risk_score=risk_score,
        risk_level=risk_level,
        factors="phone_use",
        mode="NORMAL",
    ))


# ── /api/vehicles/{plate} ─────────────────────────────────────────────────────

def test_vehicles_by_plate_found():
    store = EventStore(":memory:")
    _seed_event(store, plate="34ABC123")
    _seed_event(store, plate="34ABC123")
    _seed_event(store, plate="06XYZ789")

    result = store.vehicles_by_plate("34ABC123")
    assert len(result) == 2
    for ev in result:
        assert ev.plate == "34ABC123"
    store.close()


def test_vehicles_by_plate_not_found():
    store = EventStore(":memory:")
    result = store.vehicles_by_plate("NOTEXIST")
    assert result == []
    store.close()


def test_vehicles_by_plate_api(client):
    # Geçerli TR plaka formatı ama kayıt yok → 404
    r = client.get("/api/vehicles/34ABC1234")
    assert r.status_code == 404


def test_vehicles_by_plate_invalid_format(client):
    # Geçersiz plaka formatı → 422
    r = client.get("/api/vehicles/NOTEXIST")
    assert r.status_code == 422


def test_vehicles_api_list(client):
    r = client.get("/api/vehicles")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── /api/events/{id} ─────────────────────────────────────────────────────────

def test_event_detail_found():
    store = EventStore(":memory:")
    eid = _seed_event(store)
    ev = store.get(eid)
    assert ev is not None
    assert ev.id == eid
    store.close()


def test_event_detail_not_found():
    store = EventStore(":memory:")
    ev = store.get(99999)
    assert ev is None
    store.close()


def test_event_detail_api_not_found(client):
    r = client.get("/api/events/99999")
    assert r.status_code == 404


def test_event_detail_api_invalid_id(client):
    r = client.get("/api/events/abc")  # id integer olmalı
    assert r.status_code == 422


# ── /api/events/export ───────────────────────────────────────────────────────

def test_events_export_csv(client):
    r = client.get("/api/events/export")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "events.csv" in r.headers["content-disposition"]

    # CSV header kontrolü
    content = r.text
    assert "id,ts,plate,vtype,speed_kmh,risk_score,risk_level,factors,mode" in content


def test_events_export_with_filter(client):
    r = client.get("/api/events/export?level=MEDIUM&min_score=30")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]


# ── /camara/qod/sessions GET ─────────────────────────────────────────────────

def test_qod_sessions_list_empty(client):
    r = client.get("/camara/qod/sessions")
    assert r.status_code == 200
    data = r.json()
    assert "sessions" in data
    assert "count" in data
    assert isinstance(data["sessions"], list)


def test_qod_sessions_list_after_create(client):
    # Oturum oluştur
    create_r = client.post(
        "/camara/qod/sessions",
        json={"device": "device-guard-01", "qos_profile": "QOS_S_HIGH_THROUGHPUT"},
    )
    assert create_r.status_code == 200
    sid = create_r.json()["sessionId"]

    # Listele
    list_r = client.get("/camara/qod/sessions")
    assert list_r.status_code == 200
    data = list_r.json()
    assert data["count"] >= 1
    session_ids = [s["sessionId"] for s in data["sessions"]]
    assert sid in session_ids

    # Temizle
    client.delete(f"/camara/qod/sessions/{sid}")


def test_qod_sessions_delete_removes_from_list(client):
    create_r = client.post(
        "/camara/qod/sessions",
        json={"device": "device-guard-02", "qos_profile": "QOS_S_HIGH_THROUGHPUT"},
    )
    sid = create_r.json()["sessionId"]

    del_r = client.delete(f"/camara/qod/sessions/{sid}")
    assert del_r.status_code == 200
    assert del_r.json()["deleted"] is True

    # Silinen oturum artık listede olmamalı
    list_r = client.get("/camara/qod/sessions")
    session_ids = [s["sessionId"] for s in list_r.json()["sessions"]]
    assert sid not in session_ids


def test_qod_session_delete_not_found(client):
    r = client.delete("/camara/qod/sessions/nonexistent-session-id")
    assert r.status_code == 404


# ── /api/health zenginleştirme ───────────────────────────────────────────────

def test_health_has_new_fields(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "uptime_s" in data
    assert "event_count" in data
    assert "ws_connections" in data
    assert data["uptime_s"] >= 0
    assert data["event_count"] >= 0
    assert data["ws_connections"] >= 0


# ── /metrics (Prometheus) ────────────────────────────────────────────────────

def test_metrics_endpoint_accessible(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    content = r.text
    # Prometheus format: # HELP ve # TYPE satırları var mı
    assert "# HELP" in content or "# TYPE" in content


# ── EventStore.count() ───────────────────────────────────────────────────────

def test_event_store_count():
    store = EventStore(":memory:")
    assert store.count() == 0
    _seed_event(store)
    _seed_event(store)
    assert store.count() == 2
    store.clear()
    assert store.count() == 0
    store.close()
