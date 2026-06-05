import time
from backend.db import EventStore
from ai.schema import EventRecord


def test_event_store_add_and_filter():
    store = EventStore(":memory:")
    store.add(EventRecord(ts=time.time(), plate="34ABC123", vtype="car",
                          speed_kmh=70, risk_score=55, risk_level="MEDIUM",
                          factors="telefon_kullanimi"))
    store.add(EventRecord(ts=time.time(), plate="06XYZ789", vtype="car",
                          speed_kmh=30, risk_score=10, risk_level="LOW"))
    assert len(store.list(min_score=0)) == 2
    assert len(store.list(min_score=30)) == 1     # sadece MEDIUM+
    store.close()


def test_event_store_vehicles_grouping():
    store = EventStore(":memory:")
    for _ in range(3):
        store.add(EventRecord(ts=time.time(), plate="34ABC123", vtype="car",
                              speed_kmh=70, risk_score=55, risk_level="MEDIUM"))
    veh = store.vehicles()
    assert len(veh) == 1
    assert veh[0]["plate"] == "34ABC123"
    assert veh[0]["sightings"] == 3
    store.close()


def test_events_api_empty(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_clear_api(client):
    r = client.post("/api/clear")
    assert r.status_code == 200 and r.json()["cleared"] is True
