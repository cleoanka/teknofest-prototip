"""GET /api/settings, /.well-known/jwks.json, WS /ws/status, plate validasyon testleri."""


# ── /api/settings ────────────────────────────────────────────────────────────

def test_settings_returns_qod_config(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "qod" in data
    assert "camara_bandwidth" in data
    assert "speed" in data
    assert "require_auth" in data
    assert "rate_limit_per_min" in data


def test_settings_does_not_expose_secrets(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    # Hassas bilgiler görünmemeli
    assert "camara_client_secret" not in data
    assert "camara_client_id" not in data
    assert "db_path" not in data


def test_settings_qod_fields_complete(client):
    r = client.get("/api/settings")
    qod = r.json()["qod"]
    required_qod = [
        "eval_period_ms", "bbox_growth_threshold", "low_conf_threshold",
        "ocr_conf_threshold", "roi_line", "release_conf",
        "max_session_s", "consecutive_required",
    ]
    for field in required_qod:
        assert field in qod, f"Eksik QoD ayarı: {field}"


# ── /.well-known/jwks.json ───────────────────────────────────────────────────

def test_jwks_endpoint(client):
    r = client.get("/.well-known/jwks.json")
    assert r.status_code == 200
    data = r.json()
    assert data["issuer"] == "5g-roadguard"
    assert data["algorithm"] == "RS256"
    assert "public_key_pem" in data
    assert "BEGIN PUBLIC KEY" in data["public_key_pem"]


def test_jwks_public_key_valid_pem(client):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    r = client.get("/.well-known/jwks.json")
    pem = r.json()["public_key_pem"].encode()
    pub = load_pem_public_key(pem)
    assert pub is not None


# ── JWT key kalıcılığı ───────────────────────────────────────────────────────

def test_jwt_manager_uses_same_key_for_multiple_tokens():
    """Aynı manager instance'ı birden fazla token üretebilir ve hepsini doğrular."""
    from backend.auth import JWTManager
    mgr = JWTManager()
    tokens = [mgr.issue(f"+9053200{i:04d}") for i in range(5)]
    for t in tokens:
        payload = mgr.verify(t)
        assert payload is not None


def test_jwt_public_key_pem_exported():
    """public_key_pem() metodu geçerli PEM döndürür."""
    from backend.auth import JWTManager
    mgr = JWTManager()
    pem = mgr.public_key_pem()
    assert pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert "-----END PUBLIC KEY-----" in pem


# ── Plaka format validasyonu ──────────────────────────────────────────────────

def test_plate_validation_valid_plates(client):
    """Geçerli TR plaka formatları — 404 (kayıt yok) dönmeli, 422 değil."""
    valid_plates = ["34ABC1234", "06A1234", "35XX999", "16BCD12345"]
    for plate in valid_plates:
        r = client.get(f"/api/vehicles/{plate}")
        assert r.status_code in (404, 200), f"{plate} için beklenmeyen: {r.status_code}"


def test_plate_validation_invalid_formats(client):
    """Geçersiz formatlar 422 dönmeli."""
    invalid = ["NOTAPLAT", "abc", "ABCDE1234", "99999", "!@#$%"]
    for plate in invalid:
        r = client.get(f"/api/vehicles/{plate}")
        assert r.status_code == 422, f"{plate!r} için 422 beklendi, {r.status_code} geldi"


# ── X-Total-Count header ──────────────────────────────────────────────────────

def test_events_response_has_total_count_header(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    assert "x-total-count" in r.headers
    assert "x-filtered-count" in r.headers
    assert int(r.headers["x-total-count"]) >= 0
    assert int(r.headers["x-filtered-count"]) >= 0


def test_total_count_reflects_db_count(client):
    """X-Total-Count DB'deki tüm olayları yansıtır, filtre uygulanmaz."""
    client.post("/api/clear")
    r = client.get("/api/events")
    assert int(r.headers["x-total-count"]) == 0
    assert int(r.headers["x-filtered-count"]) == 0


# ── WS /ws/status ─────────────────────────────────────────────────────────────

def test_ws_status_sends_system_payload(client):
    with client.websocket_connect("/ws/status") as ws:
        data = ws.receive_json()
        assert "ts" in data
        assert "qod_mode" in data
        assert "bandwidth_mbps" in data
        assert "event_count" in data
        assert "ws_connections" in data
        assert "bandwidth_efficiency" in data
        assert "uptime_s" in data
        assert data["qod_mode"] in ("NORMAL", "CRITICAL")
        assert data["uptime_s"] >= 0
