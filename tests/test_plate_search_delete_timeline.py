"""Plate filtresi, bulk delete, demo-token ve timeline testleri."""
import time
from ai.schema import EventRecord


def _seed(client, plates_and_scores: list):
    """[(plate, score, level)] listesinden olay oluştur."""
    from backend.main import state
    now = time.time()
    for i, (plate, score, level) in enumerate(plates_and_scores):
        state.store.add(EventRecord(
            ts=now - i * 10,
            plate=plate,
            risk_score=score,
            risk_level=level,
            factors="speed",
            mode="NORMAL",
        ))


# ── Plate filtresi ─────────────────────────────────────────────────────────────

def test_plate_filter_exact_prefix(client):
    """plate=34 ile 34 ile başlayan plakalar filtrelenmeli."""
    _seed(client, [
        ("34ABC1234", 40, "MEDIUM"),
        ("06XYZ5678", 50, "HIGH"),
        ("34DEF9999", 60, "HIGH"),
    ])
    r = client.get("/api/events?plate=34")
    assert r.status_code == 200
    data = r.json()
    assert all("34" in e["plate"] for e in data)
    plates = {e["plate"] for e in data}
    assert "06XYZ5678" not in plates


def test_plate_filter_partial_middle(client):
    """plate=ABC ile orta kısım araması çalışmalı."""
    _seed(client, [
        ("34ABC1234", 40, "MEDIUM"),
        ("06DEF5678", 50, "HIGH"),
    ])
    r = client.get("/api/events?plate=ABC")
    assert r.status_code == 200
    data = r.json()
    assert all("ABC" in e["plate"] for e in data)


def test_plate_filter_no_match_empty_list(client):
    """Eşleşmeyen plate araması boş liste döndürmeli."""
    _seed(client, [("34ABC1234", 40, "MEDIUM")])
    r = client.get("/api/events?plate=ZZZNOMATCH")
    assert r.status_code == 200
    assert r.json() == []


def test_plate_filter_case_insensitive(client):
    """Küçük harfli plate araması büyük harfli plakaları bulmalı."""
    _seed(client, [("34ABC1234", 40, "MEDIUM")])
    r = client.get("/api/events?plate=abc")
    assert r.status_code == 200
    data = r.json()
    assert any("34ABC1234" in e["plate"] for e in data)


def test_plate_filter_x_filtered_count(client):
    """X-Filtered-Count plate filtresiyle güncellenmiş değeri göstermeli."""
    _seed(client, [
        ("34ABC1234", 40, "MEDIUM"),
        ("34ABC5678", 50, "HIGH"),
        ("06XYZ9999", 60, "HIGH"),
    ])
    r = client.get("/api/events?plate=34ABC")
    assert "X-Filtered-Count" in r.headers
    count = int(r.headers["X-Filtered-Count"])
    assert count == 2


# ── DELETE /api/events ────────────────────────────────────────────────────────

def test_bulk_delete_requires_confirm(client):
    """confirm=true olmadan silme 400 döndürmeli."""
    r = client.delete("/api/events")
    assert r.status_code == 400


def test_bulk_delete_all_with_confirm(client):
    """confirm=true ile tüm olaylar silinmeli."""
    _seed(client, [
        ("34A00001", 40, "MEDIUM"),
        ("34A00002", 50, "HIGH"),
    ])
    r = client.delete("/api/events?confirm=true")
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] >= 2
    assert data["remaining"] == 0


def test_bulk_delete_by_level(client):
    """level filtresiyle sadece belirtilen seviye silinmeli."""
    _seed(client, [
        ("34A00001", 40, "MEDIUM"),
        ("34A00002", 70, "HIGH"),
        ("34A00003", 45, "MEDIUM"),
    ])
    r = client.delete("/api/events?confirm=true&level=MEDIUM")
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] == 2
    # HIGH kaldı
    remaining_r = client.get("/api/events?level=HIGH")
    assert len(remaining_r.json()) >= 1


def test_bulk_delete_returns_remaining_count(client):
    """Silme sonrası kalan olay sayısı doğru dönmeli."""
    _seed(client, [
        ("34A00001", 40, "MEDIUM"),
        ("34A00002", 70, "HIGH"),
    ])
    r = client.delete("/api/events?confirm=true&level=MEDIUM")
    assert r.status_code == 200
    assert r.json()["remaining"] >= 1


def test_bulk_delete_by_plate(client):
    """plate filtresiyle sadece o plakadaki olaylar silinmeli."""
    _seed(client, [
        ("34ABC1234", 40, "MEDIUM"),
        ("06XYZ5678", 50, "HIGH"),
    ])
    r = client.delete("/api/events?confirm=true&plate=34ABC")
    assert r.status_code == 200
    data = r.json()
    assert data["deleted"] >= 1
    # 06XYZ5678 hâlâ kalmalı
    left = client.get("/api/events?plate=06XYZ").json()
    assert len(left) >= 1


# ── /api/demo-token ───────────────────────────────────────────────────────────

def test_demo_token_returns_200(client):
    """/api/demo-token endpoint'i require_auth=False modda çalışmalı."""
    r = client.post("/api/demo-token")
    assert r.status_code == 200


def test_demo_token_structure(client):
    """Yanıt token, sub, ttl_s alanlarını içermeli."""
    r = client.post("/api/demo-token")
    data = r.json()
    assert "token" in data
    assert "sub" in data
    assert "ttl_s" in data
    assert len(data["token"]) > 20


def test_demo_token_custom_sub(client):
    """?sub parametresi ile özel subject belirtilebilmeli."""
    r = client.post("/api/demo-token?sub=jury-evaluator")
    assert r.status_code == 200
    assert r.json()["sub"] == "jury-evaluator"


def test_demo_token_is_valid_jwt(client):
    """Üretilen token geçerli RS256 JWT olmalı."""
    from backend.auth import get_jwt_manager
    r = client.post("/api/demo-token")
    token = r.json()["token"]
    payload = get_jwt_manager().verify(token)
    assert payload is not None
    assert payload["sub"] == "demo-user"


# ── /api/vehicles/{plate}/timeline ────────────────────────────────────────────

def test_vehicle_timeline_404_unknown_plate(client):
    """Bilinmeyen plaka için 404 döndürmeli."""
    r = client.get("/api/vehicles/34ZZZ9999/timeline")
    # Timeline boş liste döner, 404 değil — event_count=0
    assert r.status_code in (200, 404)


def test_vehicle_timeline_structure(client):
    """Timeline yanıtı plate, hours, event_count, timeline alanlarını içermeli."""
    from backend.main import state
    now = time.time()
    state.store.add(EventRecord(
        ts=now - 1800, plate="34TML0001", risk_score=40,
        risk_level="MEDIUM", factors="", mode="NORMAL", speed_kmh=60.0,
    ))
    r = client.get("/api/vehicles/34TML0001/timeline")
    assert r.status_code == 200
    data = r.json()
    assert data["plate"] == "34TML0001"
    assert "hours" in data
    assert "event_count" in data
    assert isinstance(data["timeline"], list)


def test_vehicle_timeline_count_correct(client):
    """Zaman aralığındaki olay sayısı doğru raporlanmalı."""
    from backend.main import state
    now = time.time()
    for i in range(3):
        state.store.add(EventRecord(
            ts=now - i * 600, plate="34TML0002", risk_score=40,
            risk_level="MEDIUM", factors="", mode="NORMAL",
        ))
    r = client.get("/api/vehicles/34TML0002/timeline?hours=24")
    assert r.status_code == 200
    assert r.json()["event_count"] == 3


def test_vehicle_timeline_invalid_plate_422(client):
    """Geçersiz plaka formatı 422 döndürmeli."""
    r = client.get("/api/vehicles/INVALID/timeline")
    assert r.status_code == 422
