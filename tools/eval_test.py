"""Verilen ağırlığı test split'inde değerlendirir, per-sınıf mAP yazar."""
from __future__ import annotations
import sys
sys.path.insert(0, ".")
from ai.training.train import _resolve_data_yaml
from ultralytics import YOLO

def run(weights: str):
    data = _resolve_data_yaml("ai/training/data.yaml")
    m = YOLO(weights)
    r = m.val(data=data, split="test", imgsz=768, device=0, verbose=True)
    print(f"\n### {weights}")
    print(f"ALL mAP50={r.box.map50:.4f} mAP50-95={r.box.map:.4f} "
          f"P={r.box.mp:.4f} R={r.box.mr:.4f}")

if __name__ == "__main__":
    for w in sys.argv[1:]:
        run(w)
