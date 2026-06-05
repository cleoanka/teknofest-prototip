"""
Veri kümesi hazırlama yardımcıları.

1) Videodan kare çıkarma (komitenin paylaştığı senaryo videoları için).
2) YOLO klasör iskeleti oluşturma.
3) (İskelet) COCO/BDD100K alt küme süzme notları.

Kullanım:
  python -m ai.training.prepare_dataset frames  --video ornek.mp4 --out datasets/raw --fps 2
  python -m ai.training.prepare_dataset scaffold --root datasets/yolguvenligi
"""
from __future__ import annotations

import argparse
import os


def extract_frames(video: str, out: str, fps: float = 2.0) -> int:
    import cv2
    os.makedirs(out, exist_ok=True)
    cap = cv2.VideoCapture(video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / fps)))
    i, saved = 0, 0
    base = os.path.splitext(os.path.basename(video))[0]
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            cv2.imwrite(os.path.join(out, f"{base}_{saved:05d}.jpg"), frame)
            saved += 1
        i += 1
    cap.release()
    print(f"{saved} kare çıkarıldı -> {out}")
    return saved


def scaffold(root: str) -> None:
    for split in ("train", "val", "test"):
        os.makedirs(os.path.join(root, "images", split), exist_ok=True)
        os.makedirs(os.path.join(root, "labels", split), exist_ok=True)
    print(f"YOLO iskeleti hazır -> {root}")
    print("Etiketleme: labelImg / Roboflow / CVAT ile YOLO formatında etiketle.")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("frames")
    pf.add_argument("--video", required=True)
    pf.add_argument("--out", default="datasets/raw")
    pf.add_argument("--fps", type=float, default=2.0)

    ps = sub.add_parser("scaffold")
    ps.add_argument("--root", default="datasets/yolguvenligi")

    args = ap.parse_args()
    if args.cmd == "frames":
        extract_frames(args.video, args.out, args.fps)
    elif args.cmd == "scaffold":
        scaffold(args.root)


if __name__ == "__main__":
    main()
