"""
Sentetik test verisi üretici.

Gerçek/komite verisi yokken hattı ve değerlendirmeyi uçtan uca çalıştırmak için
"yaklaşan araç" senaryosu üretir: koyu arka plan üzerinde, kareler ilerledikçe
büyüyen (yaklaşan) parlak bir araç bloğu + plaka şeridi + bazı karelerde kabin
içi 'telefon' parlaklığı. Ground-truth (araç bbox, plaka var/yok, telefon var/yok)
JSON olarak kaydedilir; eval/evaluate.py bunu kullanır.

Kullanım:
  python -m mock.make_mock_video --frames 60 --out mock/sample_frames
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np


def make_frame(w: int, h: int, t: float, with_phone: bool):
    """t: 0..1 yaklaşma ilerlemesi."""
    img = np.full((h, w, 3), 18, dtype=np.uint8)  # koyu arka plan
    # araç bloğu: t arttıkça büyür ve aşağı iner (yaklaşma)
    bw = int(w * (0.18 + 0.45 * t))
    bh = int(h * (0.18 + 0.45 * t))
    cx = int(w * (0.5 + 0.05 * np.sin(t * 6)))
    cy = int(h * (0.30 + 0.40 * t))
    x1, y1 = max(0, cx - bw // 2), max(0, cy - bh // 2)
    x2, y2 = min(w, x1 + bw), min(h, y1 + bh)
    img[y1:y2, x1:x2] = (210, 210, 215)  # gövde (beyaz araç)
    # plaka şeridi (alt-orta)
    px1, px2 = x1 + bw // 4, x2 - bw // 4
    py1, py2 = y2 - max(6, bh // 8), y2 - 2
    img[py1:py2, px1:px2] = (245, 245, 250)
    phone_box = None
    if with_phone and (x2 - x1) > 30:
        # kabin içi telefon parlaklığı (sol-üst kabin)
        fx1, fy1 = x1 + bw // 3, y1 + bh // 3
        fx2, fy2 = fx1 + max(6, bw // 10), fy1 + max(8, bh // 8)
        img[fy1:fy2, fx1:fx2] = (255, 255, 255)
        phone_box = [fx1, fy1, fx2, fy2]
    gt = {"vehicle_bbox": [x1, y1, x2, y2], "plate_bbox": [px1, py1, px2, py2],
          "phone_bbox": phone_box, "area_ratio": round((bw * bh) / (w * h), 4)}
    return img, gt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=360)
    ap.add_argument("--out", default="mock/sample_frames")
    ap.add_argument("--mp4", default="mock/test_scenario.mp4")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    gts = []
    writer = None
    try:
        import cv2
        writer = cv2.VideoWriter(args.mp4, cv2.VideoWriter_fourcc(*"mp4v"),
                                 15, (args.w, args.h))
    except Exception:
        writer = None

    for i in range(args.frames):
        t = i / max(1, args.frames - 1)
        with_phone = (i % 3 == 0) and t > 0.3      # bazı karelerde telefon
        img, gt = make_frame(args.w, args.h, t, with_phone)
        gt["frame"] = i
        gts.append(gt)
        path = os.path.join(args.out, f"frame_{i:05d}.jpg")
        try:
            import cv2
            cv2.imwrite(path, img)
            if writer:
                writer.write(img)
        except Exception:
            np.save(path.replace(".jpg", ".npy"), img)

    if writer:
        writer.release()

    with open("mock/ground_truth.json", "w") as f:
        json.dump({"w": args.w, "h": args.h, "frames": gts}, f, indent=2)
    print(f"{args.frames} kare + ground_truth.json üretildi -> {args.out}")


if __name__ == "__main__":
    main()
