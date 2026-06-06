"""
İzole MediaPipe kabin demosu — gerçek modda el/yüz/kemer sinyallerini test eder.

NEDEN: tam pipeline (YOLO/torch) olmadan, yalnız MediaPipe kabin modüllerini
(`mp_cabin` + `mp_seatbelt` + yüz mesh) bir GÖRÜNTÜ veya VİDEO üzerinde koşmak için.
Tüm kareyi "sürücü ROI" sayar (kabin/yüz çekimleri için pratik).

Kullanım:
  python tools/mp_cabin_demo.py --input yol/gorsel.jpg
  python tools/mp_cabin_demo.py --input yol/video.mp4 --every-n 3 --out output/demo.mp4

Çıktı: ekrana kare-kare sinyal özeti + (video ise) annotated mp4.
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

# Proje kökünü path'e ekle (tools/ alt dizininden çalıştırınca)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import get_settings
from ai.driver_state import DriverMonitor
from ai.schema import BBox


def analyze_frame(dm: DriverMonitor, frame: np.ndarray):
    """Tüm kareyi sürücü ROI sayıp gerçek-mod sinyallerini üretir."""
    h, w = frame.shape[:2]
    full = BBox(x1=0, y1=0, x2=w, y2=h)

    # Yüz mesh (yorgunluk + ağız/kulak referansları + kimlik) — self._face_refs doldurur
    dm._face_refs = None
    ear, perclos, fatigue = dm._fatigue_real(frame, full)

    sig = None
    present = False
    signature = None
    changed = False
    if dm._face_refs:
        present = True
        refs = dm._face_refs
        sig = dm.cabin.analyze(frame, mouth_xy=refs["mouth_xy"], ear_xys=refs["ear_xys"],
                               face_width=refs["face_width"])
        signature, changed = dm._driver_identity(refs.get("feats"))

    belt = dm.seatbelt.detect(frame)

    return {
        "present": present,
        "ear": ear, "perclos": perclos, "fatigue": fatigue,
        "hands": (sig.hands_detected if sig else 0),
        "hand_near_ear": (sig.hand_near_ear if sig else False),
        "hand_near_mouth": (sig.hand_near_mouth if sig else False),
        "ear_score": (sig.ear_score if sig else 0.0),
        "mouth_score": (sig.mouth_score if sig else 0.0),
        "belt_torso": belt.torso_found,
        "belt_on": belt.belt_on,
        "no_seatbelt": belt.no_seatbelt,
        "belt_score": belt.score,
        "signature": signature,
        "driver_changed": changed,
    }


def draw_panel(frame: np.ndarray, r: dict) -> np.ndarray:
    out = frame.copy()
    lines = [
        f"yuz: {'VAR' if r['present'] else 'yok'}  el: {r['hands']}  id: {r['signature'] or '-'}",
        f"EAR: {r['ear']}  PERCLOS: {r['perclos']}  yorgun: {r['fatigue']}",
        f"el->kulak: {r['hand_near_ear']} ({r['ear_score']})  -> TELEFON",
        f"el->agiz: {r['hand_near_mouth']} ({r['mouth_score']})  -> SIGARA",
        f"kemer: torso={r['belt_torso']} on={r['belt_on']} YOK={r['no_seatbelt']} ({r['belt_score']})",
    ]
    y = 24
    for ln in lines:
        cv2.putText(out, ln, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(out, ln, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA)
        y += 26
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Görsel (jpg/png) veya video (mp4/...) yolu")
    ap.add_argument("--every-n", type=int, default=3, help="Videoda her N karede bir işle")
    ap.add_argument("--out", default="", help="Annotated video çıktı yolu (video için)")
    ap.add_argument("--roi", default="", help="Kabin kırpma (oransal x1,y1,x2,y2 0-1). Örn: 0.1,0.35,0.5,0.72")
    ap.add_argument("--upscale", type=float, default=1.0, help="Kırpılan ROI'yi bu kat büyüt (küçük/uzak yüz için)")
    ap.add_argument("--brighten", action="store_true", help="Karanlık kareyi gamma+CLAHE ile aydınlat")
    args = ap.parse_args()

    roi_frac = None
    if args.roi:
        roi_frac = [float(v) for v in args.roi.split(",")]
        assert len(roi_frac) == 4, "--roi 4 değer ister: x1,y1,x2,y2 (0-1)"

    def prep(frame):
        """Kabin ROI'sine kırp + büyüt + karanlık kareyi aydınlat (MediaPipe yüzü görsün)."""
        f = frame
        if roi_frac:
            h, w = f.shape[:2]
            x1, y1, x2, y2 = roi_frac
            f = f[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
        if args.upscale and args.upscale != 1.0 and f.size:
            f = cv2.resize(f, None, fx=args.upscale, fy=args.upscale, interpolation=cv2.INTER_CUBIC)
        # Loş otopark: gamma + CLAHE ile aydınlat (plate_ocr.super_resolve ile aynı mantık)
        if args.brighten and f.size and float(f.mean()) < 90:
            lut = np.array([((i / 255.0) ** 0.4) * 255 for i in range(256)], dtype="uint8")
            f = cv2.LUT(f, lut)
            ycrcb = cv2.cvtColor(f, cv2.COLOR_BGR2YCrCb)
            ycrcb[..., 0] = cv2.createCLAHE(2.0, (8, 8)).apply(ycrcb[..., 0])
            f = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
        return f

    if not os.path.exists(args.input):
        print(f"HATA: dosya yok: {args.input}"); sys.exit(1)

    s = get_settings()
    dm = DriverMonitor(mode="real", settings=s)
    print(f"[demo] mode: face={dm.mode} cabin={dm.cabin.mode} seatbelt={dm.seatbelt.mode}")
    if dm.mode != "real":
        print("[demo] UYARI: gerçek mod aktif değil (mediapipe yok mu?) — sinyaller boş kalır.")

    ext = os.path.splitext(args.input)[1].lower()
    is_image = ext in (".jpg", ".jpeg", ".png", ".bmp", ".webp")

    if is_image:
        frame = cv2.imread(args.input)
        if frame is None:
            print("HATA: görsel okunamadı"); sys.exit(1)
        frame = prep(frame)
        r = analyze_frame(dm, frame)
        print("[sonuç]", {k: v for k, v in r.items()})
        out_path = args.out or os.path.splitext(args.input)[0] + "_annotated.png"
        cv2.imwrite(out_path, draw_panel(frame, r))
        print(f"[demo] annotated görsel: {out_path}")
        return

    # Video
    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        print("HATA: video açılamadı"); sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    writer = None
    out_path = args.out or os.path.splitext(args.input)[0] + "_annotated.mp4"

    # Toplam sayaçlar (tespit oranı)
    agg = {"frames": 0, "face": 0, "ear": 0, "mouth": 0, "no_belt": 0, "belt_on": 0}
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if idx % max(1, args.every_n) != 0:
            continue
        frame = prep(frame)
        if writer is None:  # boyut kırpma/büyütme sonrası kesinleşir
            ph, pw = frame.shape[:2]
            writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                     fps / max(1, args.every_n), (pw, ph))
        r = analyze_frame(dm, frame)
        agg["frames"] += 1
        agg["face"] += int(r["present"])
        agg["ear"] += int(r["hand_near_ear"])
        agg["mouth"] += int(r["hand_near_mouth"])
        agg["no_belt"] += int(r["no_seatbelt"])
        agg["belt_on"] += int(r["belt_on"])
        if writer is not None:
            writer.write(draw_panel(frame, r))
        if agg["frames"] % 10 == 0:
            print(f"[kare {idx}] yuz={r['present']} el={r['hands']} "
                  f"kulak={r['hand_near_ear']} agiz={r['hand_near_mouth']} "
                  f"kemerYOK={r['no_seatbelt']}")
    cap.release()
    if writer is not None:
        writer.release()

    f = max(1, agg["frames"])
    print("\n=== ÖZET ===")
    print(f"islenen kare      : {agg['frames']}")
    print(f"yuz bulunan       : {agg['face']} (%{100*agg['face']/f:.0f})")
    print(f"el->kulak (telefon): {agg['ear']} (%{100*agg['ear']/f:.0f})")
    print(f"el->agiz (sigara) : {agg['mouth']} (%{100*agg['mouth']/f:.0f})")
    print(f"kemer takili      : {agg['belt_on']} (%{100*agg['belt_on']/f:.0f})")
    print(f"kemer YOK         : {agg['no_belt']} (%{100*agg['no_belt']/f:.0f})")
    print(f"[demo] annotated video: {out_path}")


if __name__ == "__main__":
    main()
