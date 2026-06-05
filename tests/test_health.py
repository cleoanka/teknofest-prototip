def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["ai_mode"] in ("mock", "real")
    assert "detector" in data


def test_qod_status_default_normal(client):
    r = client.get("/api/qod/status")
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "NORMAL"
    assert data["bandwidth_mbps"] == 5
    assert "bandwidth_efficiency" in data
