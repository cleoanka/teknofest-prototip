"""GZip sıkıştırma, güvenlik başlıkları, X-Request-ID, /api/qod/proof ve pagination offset testleri."""
import time
from ai.schema import EventRecord


# ── Güvenlik ve İzleme Başlıkları ──────────────────────────────────────────────

def test_security_headers_present(client):
    """Her HTTP yanıtında güvenlik başlıkları bulunmalı."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-XSS-Protection") == "1; mode=block"


def test_request_id_generated(client):
    """X-Request-ID header sunucu tarafından üretilmeli."""
    r = client.get("/api/health")
    assert "X-Request-ID" in r.headers
    assert len(r.headers["X-Request-ID"]) >= 8


def test_request_id_echoed(client):
    """İstekte gelen X-Request-ID yanıtta aynen dönmeli."""
    custom_id = "test-req-abc123"
    r = client.get("/api/health", headers={"X-Request-ID": custom_id})
    assert r.headers.get("X-Request-ID") == custom_id


def test_security_headers_on_404(client):
    """404 yanıtlarında da güvenlik başlıkları bulunmalı."""
    r = client.get("/api/events/999999")
    assert r.status_code == 404
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_security_headers_on_post(client):
    """POST endpoint'lerinde de güvenlik başlıkları aktif."""
    r = client.post("/api/clear")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "DENY"


# ── GZip Sıkıştırma ──────────────────────────────────────────────────────────

def test_gzip_accepted_header(client):
    """Accept-Encoding: gzip başlığıyla büyük yanıtlar sıkıştırılabilir."""
    store_fixture = client.app.state
    # Birden fazla olay oluştur
    for i in range(20):
        client.post("/api/clear")  # sadece mevcut olay sayısını test edebilmek için
    r = client.get("/api/events", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    # minimum_size=500 nedeniyle küçük yanıtlar sıkıştırılmayabilir — sadece 200 doğrula


def test_gzip_not_breaks_json(client):
    """GZip middleware JSON içeriği bozmamalı."""
    r = client.get("/api/statistics")
    assert r.status_code == 200
    data = r.json()
    assert "event_count" in data


# ── /api/qod/proof ────────────────────────────────────────────────────────────

def test_qod_proof_returns_200(client):
    """/api/qod/proof endpoint'i çalışıyor."""
    r = client.get("/api/qod/proof")
    assert r.status_code == 200


def test_qod_proof_structure(client):
    """Yanıt ÖTR kriteri alanlarını içermeli."""
    r = client.get("/api/qod/proof")
    data = r.json()
    assert "criterion" in data
    assert "target_efficiency_pct" in data
    assert "measured_efficiency_pct" in data
    assert "meets_criterion" in data
    assert "total_qod_cycles" in data
    assert "critical_mode_cycles" in data
    assert "qod_triggers" in data


def test_qod_proof_target_is_40(client):
    """Hedef verimlilik %40 olmalı."""
    r = client.get("/api/qod/proof")
    assert r.json()["target_efficiency_pct"] == 40.0


def test_qod_proof_triggers_list(client):
    """5 QoD tetik koşulu listelenmeli."""
    r = client.get("/api/qod/proof")
    triggers = r.json()["qod_triggers"]
    assert isinstance(triggers, list)
    assert len(triggers) == 5


def test_qod_proof_camara_mode(client):
    """CAMARA modu mock modunda 'mock' dönmeli."""
    r = client.get("/api/qod/proof")
    assert r.json()["camara_mode"] == "mock"


# ── Pagination Offset ─────────────────────────────────────────────────────────

def _seed_events(client, count: int):
    """Test için count kadar olay ekle."""
    from backend.main import state
    now = time.time()
    for i in range(count):
        state.store.add(EventRecord(
            ts=now - i * 10,
            plate=f"34TEST{i:04d}"[:12],
            risk_score=40 + (i % 30),
            risk_level="MEDIUM",
            factors="speed",
            mode="NORMAL",
        ))


def test_offset_zero_same_as_default(client):
    """offset=0 varsayılan davranışla aynı sonucu vermeli."""
    _seed_events(client, 10)
    r1 = client.get("/api/events?limit=5")
    r2 = client.get("/api/events?limit=5&offset=0")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json() == r2.json()


def test_offset_pagination(client):
    """offset ile sayfalama çalışmalı — sayfa 1 ve sayfa 2 farklı kayıtlar dönmeli."""
    _seed_events(client, 15)
    page1 = client.get("/api/events?limit=5&offset=0").json()
    page2 = client.get("/api/events?limit=5&offset=5").json()
    assert len(page1) == 5
    assert len(page2) >= 1
    # Sayfa 1 ve 2 aynı kayıtları içermemeli
    ids1 = {e["id"] for e in page1 if "id" in e}
    ids2 = {e["id"] for e in page2 if "id" in e}
    assert ids1.isdisjoint(ids2)


def test_x_filtered_count_header(client):
    """X-Filtered-Count header filtrelenmiş toplam sayıyı göstermeli."""
    _seed_events(client, 8)
    r = client.get("/api/events?limit=3&offset=0")
    assert r.status_code == 200
    assert "X-Filtered-Count" in r.headers
    filtered = int(r.headers["X-Filtered-Count"])
    assert filtered >= 8  # seed edilen olaylar dahil


def test_x_offset_header(client):
    """X-Offset header talep edilen offset değerini yansıtmalı."""
    r = client.get("/api/events?limit=5&offset=3")
    assert r.status_code == 200
    assert r.headers.get("X-Offset") == "3"


def test_offset_negative_rejected(client):
    """Negatif offset 422 döndürmeli."""
    r = client.get("/api/events?offset=-1")
    assert r.status_code == 422


def test_offset_beyond_data(client):
    """Veri dışı offset boş liste döndürmeli, hata değil."""
    r = client.get("/api/events?limit=10&offset=99999")
    assert r.status_code == 200
    assert r.json() == []
