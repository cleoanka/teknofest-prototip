"""
Gerçek model dumanı (smoke) testi.

ultralytics + torch kuruluysa gerçek YOLOv8 dedektörünü bir kare üzerinde koşturur
ve cihazı (cpu/mps/cuda) bildirir. Mac'te (Apple Silicon) MPS beklenir.

  AI_MODE=real python -m tools.smoke_real_model
"""
from __future__ import annotations

import os
import numpy as np

os.environ.setdefault("AI_MODE", "real")

from ai.detector import build_detector, resolve_mode, YoloDetector
from config.settings import get_settings


def main():
    s = get_settings()
    print("AI_MODE çözümü:", resolve_mode(s))
    det = build_detector(s)
    print("Dedektör:", type(det).__name__)
    if isinstance(det, YoloDetector):
        print("Cihaz:", det._device)
    # gerçek bir araç içeren basit kare yerine rastgele -> yine de çalışmalı
    frame = (np.random.rand(360, 640, 3) * 255).astype("uint8")
    for profile in ("normal", "critical"):
        dets = det.detect(frame, conf=s.conf_normal, profile=profile)
        print(f"  [{profile}] tespit sayısı: {len(dets)}")
    print("Gerçek model smoke testi tamam.")


if __name__ == "__main__":
    main()
