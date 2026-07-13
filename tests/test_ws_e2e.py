import base64


def _data_url(jpeg_bytes):
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()


def test_ws_ingest_returns_frame_result(client, jpeg_bytes):
    with client.websocket_connect("/ws/ingest") as ws:
        ws.send_json({"frame": _data_url(jpeg_bytes)})
        data = ws.receive_json()
        assert "frame_id" in data
        assert data["vehicle"]["present"] is True
        assert data["mode"] in ("NORMAL", "CRITICAL")
        assert "qod" in data and "risk" in data


def test_ws_ingest_triggers_qod_when_vehicle_in_roi(client, jpeg_bytes):
    """Araç ROI çizgisinde sürekli görünürse iki ardışık pozitifte KRİTİK'e geçer."""
    url = _data_url(jpeg_bytes)
    modes = []
    with client.websocket_connect("/ws/ingest") as ws:
        for _ in range(4):
            ws.send_json({"frame": url})
            modes.append(ws.receive_json()["mode"])
    assert "CRITICAL" in modes        # QoD otomatik tetiklendi


def test_ws_detections_broadcast(client, jpeg_bytes):
    """/ws/detections abonesi, ingest edilen karenin sonucunu yayın olarak alır."""
    url = _data_url(jpeg_bytes)
    with client.websocket_connect("/ws/detections") as sub:
        with client.websocket_connect("/ws/ingest") as ing:
            ing.send_json({"frame": url})
            ing.receive_json()                 # ingest yanıtı
            broadcast = sub.receive_json()      # yayın
            assert "frame_id" in broadcast
            assert broadcast["vehicle"]["present"] is True


def test_ws_handles_bad_frame(client):
    with client.websocket_connect("/ws/ingest") as ws:
        ws.send_json({"frame": "data:image/jpeg;base64,Z2FyYmFnZQ=="})
        data = ws.receive_json()
        assert "error" in data
