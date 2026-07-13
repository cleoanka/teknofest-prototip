"""
Gerçek video üzerinde QoD değerlendirmesi (gerçek model) — şartname Bölüm 8 kanıtı.

evaluate.py sentetik mock karelerde çalışır (QoD kavram kanıtı). Bu modül GERÇEK sürüş
videosunu kare kare Pipeline + QoDManager'dan geçirir ve QoD davranışını ölçer:
  - bant verimliliği (sürekli-yüksek'e göre tasarruf)
  - kritik moda ilk geçiş + kritik kare oranı
  - tespit özeti: araç tipleri (vtype), kişi/telefon, kritik modda kabin tespitleri

GT gerekmez (bant/tetikleme davranışı niceldir); doğruluk kanıtı ayrı (per-sınıf mAP).

Kullanım:
  python -m eval.qod_video --video C:/teknofest/testverisi/video_1.mp4 --stride 2
  python -m eval.qod_video --frames-dir C:/teknofest/testverisi/frames/v3_detail
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from collections import Counter
from typing import Iterator

import numpy as np

from ai.pipeline import Pipeline
from backend.qod_manager import QoDManager
from config.settings import get_settings


def iter_video(path: str, stride: int = 1) -> Iterator[np.ndarray]:
    import cv2
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"video açılamadı: {path}")
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % stride == 0:
            yield fr
        i += 1
    cap.release()


def iter_frames_dir(folder: str) -> Iterator[np.ndarray]:
    import cv2
    paths = sorted(glob.glob(os.path.join(folder, "*.jpg")) + glob.glob(os.path.join(folder, "*.png")))
    for p in paths:
        fr = cv2.imread(p)
        if fr is not None:
            yield fr


def run(frame_iter, label: str) -> dict:
    pipe = Pipeline()
    qod = QoDManager()
    s = get_settings()
    dt_s = s.qod_eval_period_ms / 1000.0

    n = crit = 0
    first_trigger = None
    vtypes: Counter = Counter()
    label_counts: Counter = Counter()
    cabin_in_critical = 0

    for frame in frame_iter:
        res, ctx = pipe.process(frame, critical=qod.is_critical)
        st = qod.step(ctx, dt_s=dt_s)
        n += 1
        if st.mode == "CRITICAL":
            crit += 1
            if first_trigger is None:
                first_trigger = n
            cabin_in_critical += sum(1 for d in res.detections
                                     if d.label in ("phone", "cigarette", "person"))
        if res.vehicle.present and res.vehicle.vtype:
            vtypes[res.vehicle.vtype] += 1
        for d in res.detections:
            label_counts[d.label] += 1

    eff = qod.bandwidth_efficiency()
    print(f"\n=== QoD (gerçek video): {label} ===")
    print(f"  işlenen kare       : {n}")
    print(f"  ilk kritik tetik   : {first_trigger}")
    print(f"  kritik kare        : {crit} (%{100*crit/n:.0f})" if n else "  kritik kare: 0")
    print(f"  bant verimliliği   : {eff:.3f}  → ~%{eff*100:.0f} tasarruf (sürekli-yüksek'e göre)")
    print(f"  kritik modda kabin : {cabin_in_critical} tespit (telefon/sigara/kişi)")
    print(f"  araç tipleri (vtype): {dict(vtypes)}")
    print(f"  tüm etiketler      : {dict(label_counts)}")
    return {"frames": n, "first_trigger": first_trigger, "critical_frames": crit,
            "bandwidth_efficiency": eff, "vtypes": dict(vtypes), "labels": dict(label_counts)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Gerçek video QoD değerlendirmesi (gerçek model)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--video", help="video dosyası (.mp4 vb.)")
    g.add_argument("--frames-dir", help="kare klasörü (sıralı .jpg/.png)")
    ap.add_argument("--stride", type=int, default=1, help="video için kare atlama (4K'da hız)")
    args = ap.parse_args()
    if args.video:
        run(iter_video(args.video, args.stride), os.path.basename(args.video))
    else:
        run(iter_frames_dir(args.frames_dir), os.path.basename(args.frames_dir.rstrip("/\\")))


if __name__ == "__main__":
    main()
