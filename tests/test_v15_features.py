"""v1.5 testleri: CORS expose_headers, /api/system/info, qod/sessions/{sid}, export plate."""
import time
from ai.schema import EventRecord


# ── CORS expose_headers ───────────────────────────────────────────────────────

def test_cors_exposes_x_total_count(client):
    """CORS Access-Control-Expose-Headers X-Total-Count içermeli."""
    r = client.get("/api/events", headers={"Origin": "http://localhost:3000"})
    exposed = r.headers.get("Access-Control-Expose-Headers", "")
    assert "X-Total-Count" in exposed


def test_cors_exposes_x_filtered_count(client):
    """CORS Access-Control-Expose-Headers X-Filtered-Count içermeli."""
    r = client.get("/api/events", headers={"Origin": "http://localhost:3000"})
    exposed = r.headers.get("Access-Control-Expose-Headers", "")
    assert "X-Filtered-Count" in exposed


def test_cors_exposes_x_request_id(client):
    """CORS Access-Control-Expose-Headers X-Request-ID içermeli."""
    r = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    exposed = r.headers.get("Access-Control-Expose-Headers", "")
    assert "X-Request-ID" in exposed


def test_cors_exposes_content_disposition(client):
    """CSV download için Content-Disposition header expose edilmeli."""
    r = client.get("/api/events", headers={"Origin": "http://localhost:3000"})
    exposed = r.headers.get("Access-Control-Expose-Headers", "")
    assert "Content-Disposition" in exposed


# ── /api/system/info ──────────────────────────────────────────────────────────

def test_system_info_200(client):
    """/api/system/info endpoint'i çalışmalı."""
    r = client.get("/api/system/info")
    assert r.status_code == 200


def test_system_info_structure(client):
    """Yanıt uptime_s, version, event_count, ws_connections içermeli."""
    r = client.get("/api/system/info")
    data = r.json()
    assert "uptime_s" in data
    assert "version" in data
    assert "event_count" in data
    assert "ws_connections" in data


def test_system_info_uptime_positive(client):
    """uptime_s pozitif olmalı."""
    r = client.get("/api/system/info")
    assert r.json()["uptime_s"] >= 0


def test_system_info_event_count_nonnegative(client):
    """event_count negatif olamaz."""
    r = client.get("/api/system/info")
    assert r.json()["event_count"] >= 0


def test_system_info_has_process_or_psutil_note(client):
    """process veya psutil mesajı bulunmalı."""
    r = client.get("/api/system/info")
    data = r.json()
    # psutil kuruluysa process + system, yoksa not
    assert "process" in data or "psutil" in data


# ── GET /camara/qod/sessions/{sid} ────────────────────────────────────────────

def test_qod_get_session_not_found(client):
    """Olmayan session ID 404 dönmeli."""
    r = client.get("/camara/qod/sessions/nonexistent-session")
    assert r.status_code == 404


def test_qod_get_session_after_create(client):
    """Oluşturulan oturum GET ile alınabilmeli."""
    create_r = client.post("/camara/qod/sessions", json={
        "device": "test-device",
        "qos_profile": "QOS_S_HIGH_THROUGHPUT",
    })
    assert create_r.status_code == 200
    sid = create_r.json()["sessionId"]

    r = client.get(f"/camara/qod/sessions/{sid}")
    assert r.status_code == 200
    data = r.json()
    assert data["sessionId"] == sid
    assert "device" in data
    assert "qosProfile" in data
    assert "ageS" in data
    assert "expired" in data


def test_qod_get_session_structure(client):
    """Oturum yanıtı tüm alanları içermeli."""
    create_r = client.post("/camara/qod/sessions", json={})
    sid = create_r.json()["sessionId"]
    r = client.get(f"/camara/qod/sessions/{sid}")
    data = r.json()
    for field in ("sessionId", "device", "qosProfile", "requestedMbps",
                  "durationS", "ageS", "status", "expired"):
        assert field in data, f"Eksik alan: {field}"


# ── /api/events/export plate filtresi ────────────────────────────────────────

def test_export_with_plate_filter(client):
    """export endpoint'i plate filtresiyle çalışmalı."""
    from backend.main import state
    now = time.time()
    state.store.add(EventRecord(
        ts=now, plate="34EXPORT01", risk_score=40,
        risk_level="MEDIUM", factors="", mode="NORMAL",
    ))
    state.store.add(EventRecord(
        ts=now - 1, plate="06OTHER999", risk_score=50,
        risk_level="HIGH", factors="", mode="NORMAL",
    ))
    r = client.get("/api/events/export?plate=34EXPORT")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    content = r.content.decode()
    assert "34EXPORT01" in content
    assert "06OTHER999" not in content


def test_export_with_level_filter(client):
    """export endpoint'i level filtresiyle çalışmalı."""
    from backend.main import state
    state.store.add(EventRecord(
        ts=time.time(), plate="34EXP0002", risk_score=90,
        risk_level="CRITICAL", factors="", mode="NORMAL",
    ))
    r = client.get("/api/events/export?level=CRITICAL")
    assert r.status_code == 200
    content = r.content.decode()
    assert "CRITICAL" in content


def test_export_content_disposition_header(client):
    """CSV export Content-Disposition: attachment header içermeli."""
    r = client.get("/api/events/export")
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "events.csv" in cd
