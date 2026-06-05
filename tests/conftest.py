"""Test ortak yapılandırması — deterministik MOCK YZ modu, bellek-içi DB."""
import os

# Modeller indirilmeden, deterministik testler için mock mod.
os.environ.setdefault("AI_MODE", "mock")
os.environ.setdefault("DB_PATH", ":memory:")

import numpy as np
import pytest


@pytest.fixture
def synthetic_frame():
    """Koyu zeminde parlak araç bloğu — mock dedektörün bulacağı kare."""
    img = np.full((360, 640, 3), 20, dtype=np.uint8)
    img[120:300, 200:480] = 220          # araç
    img[280:298, 280:400] = 250          # plaka şeridi
    return img


@pytest.fixture
def jpeg_bytes(synthetic_frame):
    import cv2
    ok, buf = cv2.imencode(".jpg", synthetic_frame)
    assert ok
    return buf.tobytes()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        yield c
