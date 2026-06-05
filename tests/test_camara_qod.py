import time
from backend.camara.qod import MockQoDProvider
from config.settings import Settings


def test_create_and_bandwidth():
    p = MockQoDProvider(Settings())
    assert p.current_bandwidth_mbps() == 5          # normal
    sess = p.create_session(device="d1", duration_s=5)
    assert p.active_session_id == sess.id
    assert p.current_bandwidth_mbps() == 20         # kritik
    assert p.current_latency_ms() < Settings().camara_network_latency_ms


def test_delete_releases_bandwidth():
    p = MockQoDProvider(Settings())
    sess = p.create_session(device="d1", duration_s=5)
    assert p.delete_session(sess.id) is True
    assert p.active_session_id is None
    assert p.current_bandwidth_mbps() == 5


def test_session_auto_expire():
    p = MockQoDProvider(Settings())
    p.create_session(device="d1", duration_s=0.05)
    time.sleep(0.08)
    assert p.active_session_id is None
    assert p.current_bandwidth_mbps() == 5


def test_api_create_delete(client):
    r = client.post("/camara/qod/sessions", json={"device": "device-guard-01", "duration_s": 5})
    assert r.status_code == 200
    sid = r.json()["sessionId"]
    assert r.json()["requestedMbps"] == 20

    r2 = client.delete(f"/camara/qod/sessions/{sid}")
    assert r2.status_code == 200 and r2.json()["deleted"] is True

    r3 = client.delete(f"/camara/qod/sessions/{sid}")
    assert r3.status_code == 404
