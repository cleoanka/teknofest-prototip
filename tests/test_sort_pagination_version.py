"""Events sort, vehicles pagination ve /api/version testleri."""
import time
import pytest
from ai.schema import EventRecord


def _seed(client, count: int = 10):
    """Test için çeşitli risk skorlarına sahip olaylar oluştur."""
    from backend.main import state
    now = time.time()
    for i in range(count):
        state.store.add(EventRecord(
            ts=now - i * 5,
            plate=f"06TEST{i:04d}"[:12],
            risk_score=10 + i * 5,
            risk_level="MEDIUM" if i < 5 else "HIGH",
            factors="speed",
            mode="NORMAL",
            speed_kmh=float(50 + i * 3),
        ))


# ── /api/events sort ──────────────────────────────────────────────────────────

def test_sort_by_ts_desc_default(client):
    """Varsayılan sıralama ts DESC olmalı — en yeni önce."""
    _seed(client, 5)
    r = client.get("/api/events?limit=5")
    assert r.status_code == 200
    data = r.json()
    timestamps = [e["ts"] for e in data]
    assert timestamps == sorted(timestamps, reverse=True)


def test_sort_by_ts_asc(client):
    """sort_by=ts&sort_dir=asc: en eski önce."""
    _seed(client, 5)
    r = client.get("/api/events?sort_by=ts&sort_dir=asc&limit=5")
    assert r.status_code == 200
    data = r.json()
    timestamps = [e["ts"] for e in data]
    assert timestamps == sorted(timestamps)


def test_sort_by_risk_score_desc(client):
    """sort_by=risk_score&sort_dir=desc: en yüksek risk önce."""
    _seed(client, 8)
    r = client.get("/api/events?sort_by=risk_score&sort_dir=desc&limit=8")
    assert r.status_code == 200
    data = r.json()
    scores = [e["risk_score"] for e in data]
    assert scores == sorted(scores, reverse=True)


def test_sort_by_risk_score_asc(client):
    """sort_by=risk_score&sort_dir=asc: en düşük risk önce."""
    _seed(client, 8)
    r = client.get("/api/events?sort_by=risk_score&sort_dir=asc&limit=8")
    assert r.status_code == 200
    data = r.json()
    scores = [e["risk_score"] for e in data]
    assert scores == sorted(scores)


def test_sort_invalid_col_falls_back_to_ts(client):
    """Geçersiz sort_by değeri varsayılan ts sıralamasına düşmeli — 422 vermemeli."""
    r = client.get("/api/events?sort_by=injected_col&sort_dir=desc")
    assert r.status_code == 200


def test_sort_invalid_dir_falls_back_to_desc(client):
    """Geçersiz sort_dir değeri varsayılan desc'e düşmeli — 422 vermemeli."""
    r = client.get("/api/events?sort_by=ts&sort_dir=INVALID")
    assert r.status_code == 200


def test_sort_combined_with_filter(client):
    """sort + level filtresi birlikte çalışmalı."""
    _seed(client, 10)
    r = client.get("/api/events?sort_by=risk_score&sort_dir=asc&level=HIGH")
    assert r.status_code == 200
    data = r.json()
    for e in data:
        assert e["risk_level"] == "HIGH"


# ── /api/vehicles pagination ──────────────────────────────────────────────────

def test_vehicles_offset_zero(client):
    """offset=0 ile /api/vehicles aynı sonuç vermeli."""
    r1 = client.get("/api/vehicles?limit=10")
    r2 = client.get("/api/vehicles?limit=10&offset=0")
    assert r1.status_code == 200
    assert r1.json() == r2.json()


def test_vehicles_x_total_count_header(client):
    """X-Total-Count header benzersiz plaka sayısını vermeli."""
    _seed(client, 6)
    r = client.get("/api/vehicles?limit=3")
    assert r.status_code == 200
    assert "X-Total-Count" in r.headers
    total = int(r.headers["X-Total-Count"])
    assert total >= 1


def test_vehicles_x_offset_header(client):
    """X-Offset header talep edilen değeri yansıtmalı."""
    r = client.get("/api/vehicles?limit=5&offset=2")
    assert r.status_code == 200
    assert r.headers.get("X-Offset") == "2"


def test_vehicles_pagination_pages_differ(client):
    """vehicles_count yeterince büyükse sayfa 1 ve 2 farklı plakalar dönmeli."""
    _seed(client, 20)
    page1 = client.get("/api/vehicles?limit=5&offset=0").json()
    page2 = client.get("/api/vehicles?limit=5&offset=5").json()
    if len(page1) > 0 and len(page2) > 0:
        plates1 = {r["plate"] for r in page1}
        plates2 = {r["plate"] for r in page2}
        assert plates1.isdisjoint(plates2)


def test_vehicles_negative_offset_rejected(client):
    """Negatif offset 422 döndürmeli."""
    r = client.get("/api/vehicles?offset=-1")
    assert r.status_code == 422


# ── /api/version ──────────────────────────────────────────────────────────────

def test_version_endpoint_200(client):
    """/api/version endpoint'i 200 dönmeli."""
    r = client.get("/api/version")
    assert r.status_code == 200


def test_version_structure(client):
    """Yanıt version, python, ai_mode, uptime_s alanlarını içermeli."""
    r = client.get("/api/version")
    data = r.json()
    assert "version" in data
    assert "python" in data
    assert "ai_mode" in data
    assert "uptime_s" in data
    assert "camara_mode" in data
    assert "build" in data


def test_version_is_140(client):
    """Versiyon 1.4.0 olmalı."""
    r = client.get("/api/version")
    assert r.json()["version"] == "1.4.0"


def test_version_ai_mode_mock(client):
    """Test ortamında ai_mode mock olmalı."""
    r = client.get("/api/version")
    assert r.json()["ai_mode"] == "mock"


def test_version_camara_mode_mock(client):
    """Test ortamında camara_mode mock olmalı."""
    r = client.get("/api/version")
    assert r.json()["camara_mode"] == "mock"
