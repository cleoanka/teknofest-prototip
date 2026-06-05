"""
Model fine-tuning / transfer learning hattı (ultralytics YOLOv8).

Eğitilmiş model henüz yok → COCO ön-eğitimli ağırlıklardan başlayıp komite verisi
geldiğinde fine-tune ediyoruz. Transkriptteki yaklaşıma uygun: açık kaynak
setlerle başla, TOGG/etiketli set gelince ince ayar yap. Augmentation (mozaik,
renk jitter, gece/yağmur), 70/15/15 video-bazlı bölme önerilir.

Kullanım:
  python -m ai.training.train --data ai/training/data.yaml --base yolov8s.pt \
      --epochs 80 --imgsz 640 --device auto

Çıktı: runs/detect/train*/weights/best.pt  ->  config'te YOLO_MODEL_CRITICAL yap.
"""
from __future__ import annotations

import argparse


def main():
    ap = argparse.ArgumentParser(description="YOL Güvenliği YOLO fine-tune")
    ap.add_argument("--data", default="ai/training/data.yaml")
    ap.add_argument("--base", default="yolov8s.pt", help="başlangıç ağırlığı (COCO)")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="auto", help="auto|cpu|mps|cuda|0")
    ap.add_argument("--name", default="yolguvenligi")
    ap.add_argument("--export-int8", action="store_true",
                    help="eğitimden sonra INT8/ONNX/TensorRT export")
    args = ap.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("ultralytics kurulu değil: pip install ultralytics")

    device = args.device
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else (
                "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
        except Exception:
            device = "cpu"

    model = YOLO(args.base)
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        name=args.name,
        # —— augmentation (genelleme: farklı araç/açı/hava — şartname gereği) ——
        mosaic=1.0,
        mixup=0.1,
        hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,   # renk jitter
        degrees=5.0, translate=0.1, scale=0.5, fliplr=0.5,
        # —— nadir sınıf dengesizliği için (yorgunluk/kaza nadirdir) ——
        # focal loss benzeri etki: cls ağırlığını artır
        cls=0.7,
        patience=20,
        seed=42,
    )

    metrics = model.val(data=args.data, device=device, split="test")
    print("mAP50:", getattr(metrics.box, "map50", None),
          "mAP50-95:", getattr(metrics.box, "map", None))

    if args.export_int8:
        # Mac/NVIDIA için gecikme-doğruluk dengesi (ÖTR: TensorRT INT8 ~%20-35 hız)
        model.export(format="onnx", int8=True, imgsz=args.imgsz)
        print("Export tamam (ONNX/INT8).")


if __name__ == "__main__":
    main()
