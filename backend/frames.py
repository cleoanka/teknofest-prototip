"""Kare çözümleme/kodlama yardımcıları (JPEG <-> numpy)."""
from __future__ import annotations

import base64
from typing import Optional

import numpy as np


def decode_jpeg(data: bytes) -> Optional[np.ndarray]:
    if not data:
        return None
    try:
        import cv2
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except Exception:
        pass
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(data)).convert("RGB")
        return np.asarray(img)[:, :, ::-1].copy()  # RGB->BGR
    except Exception:
        return None


def decode_data_url(data_url: str) -> Optional[np.ndarray]:
    """'data:image/jpeg;base64,...' veya düz base64 -> numpy BGR."""
    if not data_url:
        return None
    b64 = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        return decode_jpeg(base64.b64decode(b64))
    except Exception:
        return None


def encode_jpeg_b64(frame: np.ndarray, quality: int = 60) -> Optional[str]:
    try:
        import cv2
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return None
