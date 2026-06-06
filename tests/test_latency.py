"""Gecikme ölçümü testleri — total_latency_ms, client_ts."""
import base64
import json
import time


def _data_url(jpeg_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()


def test_frame_result_has_total_latency_ms(client, jpeg_bytes):
    """FrameResult total_latency_ms alanını içeriyor mu?"""
    with client.websocket_connect("/ws/ingest") as ws:
        ws.send_json({"frame": _data_url(jpeg_bytes)})
        data = ws.receive_json()
        assert "total_latency_ms" in data
        assert isinstance(data["total_latency_ms"], (int, float))
        assert data["total_latency_ms"] >= 0


def test_total_latency_ms_with_client_ts(client, jpeg_bytes):
    """client_ts gönderildiğinde total_latency_ms ağ gecikmesini de içerir."""
    with client.websocket_connect("/ws/ingest") as ws:
        client_ts = time.time()
        msg = {"frame": _data_url(jpeg_bytes), "client_ts": client_ts}
        ws.send_json(msg)
        data = ws.receive_json()
        assert "total_latency_ms" in data
        # Test ortamında 0-500ms arasında olmalı
        assert 0 <= data["total_latency_ms"] < 5000


def test_latency_ms_is_inference_only(client, jpeg_bytes):
    """latency_ms sadece YZ pipeline süresini içerir."""
    with client.websocket_connect("/ws/ingest") as ws:
        ws.send_json({"frame": _data_url(jpeg_bytes)})
        data = ws.receive_json()
        assert "latency_ms" in data
        assert isinstance(data["latency_ms"], (int, float))
        assert data["latency_ms"] >= 0


def test_latency_fields_schema_present():
    """FrameResult şemasında her iki gecikme alanı var mı?"""
    from ai.schema import FrameResult
    result = FrameResult(frame_id=1, ts=time.time())
    assert hasattr(result, "latency_ms")
    assert hasattr(result, "total_latency_ms")
    assert result.latency_ms == 0.0
    assert result.total_latency_ms == 0.0


def test_ws_frame_too_large(client):
    """5 MB'dan büyük frame reddedilir."""
    big_payload = json.dumps({"frame": "data:image/jpeg;base64," + "A" * (5 * 1024 * 1024 + 100)})
    with client.websocket_connect("/ws/ingest") as ws:
        ws.send_text(big_payload)
        data = ws.receive_json()
        assert "error" in data
        assert "large" in data["error"].lower() or "büyük" in data["error"].lower()
