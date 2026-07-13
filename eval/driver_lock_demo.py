"""
Sürücü KİMLİK KİLİDİ demosu — gerçek video üzerinde (ai/driver_state.py).

Amaç: "aynı kişi N kare sürücü seçilince kilitlenir, araç yarı çıkıp sürücü
kutusu kaybolsa bile sürücü arka koltuğa atlamaz" davranışını gerçek footage'ta
GÖSTERMEK. Her kare için kilit durumunu (aday sayımı / kilit / kayıp-TTL) raporlar
ve seçilmiş anlarda annotasyonlu kare (küçültülmüş JPG) kaydeder.

Kullanım:
  python -m eval.driver_lock_demo --video C:/teknofest/testverisi/video_1.mp4 \
         --stride 1 --out-dir eval/out/lock_v1

Gerçek mod (AI_MODE=real) + ultralytics + GPU ister. Çıktı: konsol zaman çizelgesi
+ out-dir altında annotasyonlu kareler. Otomatik teste dâhil DEĞİL (model/GPU ister).
"""
from __future__ import annotations

import argparse
import os
from typing import Optional

import cv2

os.environ.setdefault("AI_MODE", "real")

from ai.pipeline import Pipeline
from ai.schema import BBox


def _draw_box(img, b: Optional[BBox], color, label: str):
    if b is None:
        return
    x1, y1, x2, y2 = int(b.x1), int(b.y1), int(b.x2), int(b.y2)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
    if label:
        ((tw, th), _) = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.rectangle(img, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), color, -1)
        cv2.putText(img, label, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (255, 255, 255), 2, cv2.LINE_AA)


def _persons_in_cabin(res, dm):
    """Kabindeki person tespitlerini (id, bbox) döndürür — kilit raporu için."""
    vb = res.vehicle.bbox
    if vb is None:
        return []
    out = []
    for d in res.detections:
        if d.label == "person" and dm._center_in(d.bbox, vb):
            out.append((d.track_id, d.bbox))
    return out


def main():
    ap = argparse.ArgumentParser(description="Sürücü kimlik kilidi demosu (gerçek video)")
    ap.add_argument("--video", required=True)
    ap.add_argument("--stride", type=int, default=1, help="kare atlama (4K'da hız)")
    ap.add_argument("--max-frames", type=int, default=0, help="0 = tümü")
    ap.add_argument("--out-dir", default="eval/out/lock_demo")
    ap.add_argument("--save-every", type=int, default=0,
                    help=">0 ise her N işlenen karede bir annotasyon JPG kaydet")
    ap.add_argument("--write-video", default="",
                    help="izlenebilir annotasyonlu MP4 yolu (her kare, yarı çözünürlük)")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"video açılamadı: {args.video}")

    pipe = Pipeline()
    dm = pipe.driver

    fidx = -1
    processed = 0
    prev_lock = {}          # vid -> kilitli id (geçiş tespiti için)
    prev_persons_present = True
    lock_events = []        # (frame, mesaj)
    missing_runs = []       # kilitliyken sürücünün kaç kare kayıp olduğu serileri
    cur_missing = 0
    saved = 0
    writer = None

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        fidx += 1
        if args.stride > 1 and (fidx % args.stride):
            continue
        if args.max_frames and processed >= args.max_frames:
            break
        processed += 1

        res, _ = pipe.process(frame, critical=True)
        vb = res.vehicle.bbox
        vid = res.vehicle.track_id if res.vehicle.track_id is not None else -1
        persons = _persons_in_cabin(res, dm)
        person_ids = [p[0] for p in persons]
        locked_id = dm._driver_lock.get(vid)
        cand = dm._driver_cand.get(vid)
        miss = dm._driver_miss.get(vid, 0)
        drv_box = res.vehicle.driver_bbox
        driver_present = locked_id is not None and locked_id in person_ids

        # Kilit kuruldu geçişi
        if locked_id is not None and prev_lock.get(vid) != locked_id:
            lock_events.append((fidx, f"KİLİT KURULDU → sürücü id={locked_id} (araç vid={vid})"))
        # Kilit bırakıldı geçişi
        if prev_lock.get(vid) is not None and locked_id is None:
            lock_events.append((fidx, f"kilit bırakıldı (TTL doldu, araç vid={vid})"))
        prev_lock[vid] = locked_id

        # Kilitliyken sürücü kayıp serileri (asıl kanıt: atlamıyor)
        if locked_id is not None and not driver_present:
            cur_missing += 1
        else:
            if cur_missing > 0:
                missing_runs.append(cur_missing)
            cur_missing = 0

        # Durum metni — ASCII (OpenCV Hershey fontu Türkçe karakter basamaz)
        if locked_id is None:
            state = f"ADAY id={cand[0] if cand else None} say={cand[1] if cand else 0}"
        elif driver_present:
            state = f"LOCKED surucu id={locked_id} MEVCUT"
        else:
            state = (f"LOCKED id={locked_id} KAYIP({miss}/{dm.s.driver_lock_ttl}) "
                     f"-> surucu ATLAMAZ")
        changed = (len(person_ids) == 0) != (not prev_persons_present)
        prev_persons_present = len(person_ids) > 0
        if processed <= 3 or changed or locked_id != prev_lock.get(vid, "x"):
            print(f"f{fidx:04d} | kisi={person_ids} | surucu_kutu={'var' if drv_box else 'YOK'} | {state}")

        # ── Annotasyon (video için HER kare; JPG için seçili anlar) ──
        need_vis = bool(writer is not None or args.write_video)
        do_jpg = bool(args.save_every and processed % args.save_every == 0)
        if locked_id is not None and not driver_present and saved < 12:
            do_jpg = True   # asıl ilginç an: kilitli ama kayıp
        if need_vis or do_jpg:
            vis = frame.copy()
            for pid, pb in persons:
                is_drv = (pid == locked_id)
                _draw_box(vis, pb, (0, 0, 255) if is_drv else (0, 165, 255),
                          f"{'SURUCU' if is_drv else 'YOLCU'} id={pid}")
            if drv_box is not None:
                tag = f"DRIVER ROI {'LOCKED id='+str(locked_id) if locked_id else ''}"
                _draw_box(vis, drv_box, (255, 0, 0), tag)
            cv2.putText(vis, f"frame {fidx}  {state}", (30, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 255), 3, cv2.LINE_AA)
            small = cv2.resize(vis, (vis.shape[1] // 2, vis.shape[0] // 2))
            if args.write_video:
                if writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    out_fps = max(1.0, (cap.get(cv2.CAP_PROP_FPS) or 25) / max(1, args.stride))
                    writer = cv2.VideoWriter(args.write_video, fourcc, out_fps,
                                             (small.shape[1], small.shape[0]))
                writer.write(small)
            if do_jpg:
                cv2.imwrite(os.path.join(args.out_dir, f"f{fidx:04d}.jpg"), small)
                saved += 1

    if cur_missing > 0:
        missing_runs.append(cur_missing)
    cap.release()
    if writer is not None:
        writer.release()

    print("\n========== KİLİT ZAMAN ÇİZELGESİ ==========")
    for f, m in lock_events:
        print(f"  f{f:04d}: {m}")
    if not lock_events:
        print("  (kilit kurulmadı — yeterli ardışık kare sürücü seçilemedi)")
    print(f"\nİşlenen kare: {processed}")
    print(f"Sürücü-kilidi eşiği (driver_lock_frames): {dm.s.driver_lock_frames}")
    print(f"Kayıp-koruma penceresi (driver_lock_ttl):  {dm.s.driver_lock_ttl}")
    if missing_runs:
        print(f"Kilitliyken sürücünün KAYIP olduğu seriler (kare): {missing_runs}")
        print(f"  → bu serilerde sürücü kimliği SABİT kaldı, başkasına atlamadı.")
    print(f"Kaydedilen annotasyonlu kare: {saved}  (klasör: {args.out_dir})")
    if args.write_video:
        print(f"İzlenebilir video: {os.path.abspath(args.write_video)}")


if __name__ == "__main__":
    main()
