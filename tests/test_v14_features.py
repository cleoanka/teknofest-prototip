"""v1.4 özellik testleri: /api/health/deep, X-Response-Time, WS token auth, JSON logging, OpenAPI."""
import time
import pytest


# ── /api/health/deep ──────────────────────────────────────────────────────────

def test_health_deep_returns_200(client):
    r = client.get("/api/health/deep")
    assert r.status_code == 200


def test_health_deep_structure(client):
    """Yanıt status, checks, uptime_s, version alanlarını içermeli."""
    r = client.get("/api/health/deep")
    data = r.json()
    assert data["status"] in ("ok", "degraded")
    assert "checks" in data
    assert "uptime_s" in data
    assert "version" in data
    assert "ws_connections" in data


def test_health_deep_db_check(client):
    """DB kontrolü 'ok' statüsüyle dönmeli."""
    r = client.get("/api/health/deep")
    checks = r.json()["checks"]
    assert "db" in checks
    assert checks["db"]["status"] == "ok"
    assert "event_count" in checks["db"]


def test_health_deep_qod_check(client):
    """QoD kontrolü 'ok' statüsüyle dönmeli."""
    r = client.get("/api/health/deep")
    checks = r.json()["checks"]
    assert "qod" in checks
    assert checks["qod"]["status"] == "ok"
    assert "mode" in checks["qod"]


def test_health_deep_memory_check(client):
    """Bellek kontrolü bulunmalı (ok veya unavailable)."""
    r = client.get("/api/health/deep")
    checks = r.json()["checks"]
    assert "memory" in checks
    assert checks["memory"]["status"] in ("ok", "unavailable")


def test_health_deep_version_is_140(client):
    """API versiyonu 1.4.0 olmalı."""
    r = client.get("/api/health/deep")
    assert r.json()["version"] == "1.4.0"


# ── X-Response-Time header ────────────────────────────────────────────────────

def test_x_response_time_present(client):
    """Her yanıtta X-Response-Time header bulunmalı."""
    r = client.get("/api/health")
    assert "X-Response-Time" in r.headers


def test_x_response_time_format(client):
    """X-Response-Time 'NNNms' formatında olmalı."""
    r = client.get("/api/health")
    val = r.headers["X-Response-Time"]
    assert val.endswith("ms")
    ms = float(val.replace("ms", ""))
    assert ms >= 0


def test_x_response_time_on_post(client):
    """POST endpoint'lerinde de X-Response-Time aktif."""
    r = client.post("/api/clear")
    assert "X-Response-Time" in r.headers


# ── WS Token Auth ─────────────────────────────────────────────────────────────

def test_ws_ingest_no_auth_required(client):
    """require_auth=False ile token olmadan WS bağlantısı kabul edilmeli."""
    with client.websocket_connect("/ws/ingest") as ws:
        assert ws is not None  # bağlantı başarılı


def test_ws_detections_no_auth_required(client):
    """require_auth=False ile /ws/detections token olmadan çalışmalı."""
    with client.websocket_connect("/ws/detections") as ws:
        assert ws is not None


def test_ws_status_no_auth_required(client):
    """require_auth=False ile /ws/status token olmadan çalışmalı."""
    with client.websocket_connect("/ws/status") as ws:
        data = ws.receive_json()
        assert "qod_mode" in data


def test_ws_auth_with_valid_token(client):
    """Geçerli token ile WS bağlantısı kabul edilmeli (require_auth=False modda da)."""
    from backend.auth import get_jwt_manager
    token = get_jwt_manager().issue("test-user")
    with client.websocket_connect(f"/ws/detections?token={token}") as ws:
        assert ws is not None


# ── Swagger / OpenAPI ──────────────────────────────────────────────────────────

def test_openapi_schema_accessible(client):
    """/openapi.json erişilebilir olmalı."""
    r = client.get("/openapi.json")
    assert r.status_code == 200


def test_openapi_has_tags(client):
    """OpenAPI şeması tag tanımlarını içermeli."""
    r = client.get("/openapi.json")
    schema = r.json()
    assert "tags" in schema
    tag_names = [t["name"] for t in schema["tags"]]
    assert "system" in tag_names
    assert "events" in tag_names
    assert "camara" in tag_names
    assert "analytics" in tag_names


def test_openapi_version_140(client):
    """OpenAPI bilgi bölümünde versiyon 1.4.0 olmalı."""
    r = client.get("/openapi.json")
    info = r.json()["info"]
    assert info["version"] == "1.4.0"


def test_docs_accessible(client):
    """/docs Swagger UI sayfası erişilebilir olmalı."""
    r = client.get("/docs")
    assert r.status_code == 200


# ── JSON Logging ───────────────────────────────────────────────────────────────

def test_json_logger_importable():
    """roadguard logger backend.main'den erişilebilir olmalı."""
    import logging
    lgr = logging.getLogger("roadguard")
    assert lgr is not None


def test_json_formatter_output():
    """_JsonFormatter geçerli JSON satırı üretmeli."""
    import logging
    from backend.main import _JsonFormatter
    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO,
        pathname="", lineno=0, msg="test mesajı",
        args=(), exc_info=None,
    )
    import json
    line = formatter.format(record)
    parsed = json.loads(line)
    assert parsed["level"] == "INFO"
    assert parsed["msg"] == "test mesajı"
    assert "ts" in parsed
    assert "logger" in parsed
