#!/usr/bin/env python3
"""
Video test aracı — video dosyasını tam (veya yarım) çözünürlükte işler.

Kullanım:
    python tools/test_video.py project-files/test-verisi/video_3.mp4
    python tools/test_video.py video.mp4 --every 3 --scale 0.5 --out output/result.mp4
    python tools/test_video.py video.mp4 --no-display --json-out results.json

Çıktı:
  - Annotated video (--out) ile plaka kutusu (sarı), araç kutusu (yeşil),
    sürücü ROI (mavi), yolcu ROI (turuncu), kişiler (beyaz)
  - JSON özeti (plaka, hız, swerving, risk)
  - Terminal istatistikleri
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Optional, List

# Proje kökünü sys.path'e ekle (tools/ klasöründen çalıştırılırken)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np

# Renk tanımları (BGR)
CLR_VEHICLE  = (0, 200, 0)       # Yeşil — araç kutusu
CLR_PLATE    = (0, 220, 255)      # Sarı — plaka kutusu
CLR_DRIVER   = (255, 120, 0)      # Mavi — sürücü ROI
CLR_PASSENGER = (0, 120, 255)     # Turuncu — yolcu ROI
CLR_PERSON   = (255, 255, 255)    # Beyaz — kişi tespiti
CLR_PHONE    = (0, 0, 255)        # Kırmızı — telefon
CLR_SWERVING = (0, 0, 220)        # Kırmızı — swerving uyarısı


def draw_box(img, x1, y1, x2, y2, color, label: str = "", thickness: int = 2):
    try:
        import cv2
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
        if label:
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 8, y1), color, -1)
            cv2.putText(img, label, (x1 + 4, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    except Exception:
        pass


def annotate_frame(frame: np.ndarray, result_dict: dict) -> np.ndarray:
    """FrameResult dict'inden alınan sonuçları kareye çiz."""
    try:
        import cv2
    except ImportError:
        return frame

    annotated = frame.copy()
    h, w = annotated.shape[:2]

    vehicle = result_dict.get("vehicle", {})
    driver_state = result_dict.get("driver", {})
    risk = result_dict.get("risk", {})

    # Araç kutusu
    vbbox = vehicle.get("bbox")
    if vbbox:
        plate_text = vehicle.get("plate", {}).get("text") or ""
        speed = vehicle.get("speed_kmh")
        swerving = vehicle.get("swerving", False)
        vtype = vehicle.get("vtype") or "araç"
        label_parts = [vtype]
        if plate_text:
            label_parts.append(plate_text)
        if speed is not None:
            label_parts.append(f"{speed} km/h")
        veh_label = " | ".join(label_parts)
        color = CLR_SWERVING if swerving else CLR_VEHICLE
        draw_box(annotated, vbbox["x1"], vbbox["y1"], vbbox["x2"], vbbox["y2"],
                 color, veh_label, thickness=3)
        if swerving:
            cv2.putText(annotated, "⚠ SWERVING", (int(vbbox["x1"]), int(vbbox["y2"]) + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, CLR_SWERVING, 2, cv2.LINE_AA)

    # Plaka kutusu (sarı) — araç kutusundan ayrı
    pbbox = vehicle.get("plate_bbox")
    if pbbox:
        plate_text = vehicle.get("plate", {}).get("text") or "?"
        draw_box(annotated, pbbox["x1"], pbbox["y1"], pbbox["x2"], pbbox["y2"],
                 CLR_PLATE, f"PLAKA: {plate_text}", thickness=2)

    # Sürücü ROI (mavi)
    dbbox = vehicle.get("driver_bbox")
    if dbbox:
        phone_label = " [TELEFON!]" if driver_state.get("phone_use") else ""
        draw_box(annotated, dbbox["x1"], dbbox["y1"], dbbox["x2"], dbbox["y2"],
                 CLR_DRIVER, f"SÜRÜCÜ{phone_label}", thickness=1)

    # Yolcu ROI (turuncu)
    psbbox = vehicle.get("passenger_bbox")
    if psbbox:
        pax_phone = " [telefon]" if driver_state.get("passenger_phone") else ""
        draw_box(annotated, psbbox["x1"], psbbox["y1"], psbbox["x2"], psbbox["y2"],
                 CLR_PASSENGER, f"YOLCU{pax_phone}", thickness=1)

    # Tespit edilen nesneler (kişi, telefon)
    for det in result_dict.get("detections", []):
        lbl = det.get("label", "")
        bb = det.get("bbox", {})
        if lbl == "phone":
            draw_box(annotated, bb["x1"], bb["y1"], bb["x2"], bb["y2"],
                     CLR_PHONE, f"telefon {det.get('confidence', 0):.0%}")
        elif lbl == "person":
            draw_box(annotated, bb["x1"], bb["y1"], bb["x2"], bb["y2"],
                     CLR_PERSON, f"kişi {det.get('confidence', 0):.0%}")

    # Risk skoru (sağ üst)
    score = risk.get("score", 0)
    level = risk.get("level", "LOW")
    factors = ", ".join(risk.get("factors", []))
    risk_color = (0, 0, 200) if score >= 85 else (0, 128, 255) if score >= 60 else (0, 200, 255) if score >= 30 else (0, 200, 0)
    cv2.rectangle(annotated, (w - 260, 10), (w - 10, 90), (20, 20, 20), -1)
    cv2.putText(annotated, f"Risk: {score}/100 [{level}]", (w - 250, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, risk_color, 1, cv2.LINE_AA)
    if factors:
        cv2.putText(annotated, factors[:35], (w - 250, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1, cv2.LINE_AA)

    # Kare bilgisi (sol üst)
    frame_id = result_dict.get("frame_id", 0)
    latency = result_dict.get("latency_ms", 0)
    plate_text = vehicle.get("plate", {}).get("text") or ""
    info = f"Kare #{frame_id} | {latency:.0f}ms"
    if plate_text:
        info += f" | {plate_text}"
    cv2.putText(annotated, info, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1, cv2.LINE_AA)

    return annotated


def process_video(
    video_path: str,
    every_n: int = 2,
    scale: float = 1.0,
    out_path: Optional[str] = None,
    max_frames: Optional[int] = None,
    show_display: bool = False,
    json_out: Optional[str] = None,
) -> dict:
    """
    Videoyu işler. Sonuç dict'i döner.

    Parametreler:
        video_path: Giriş video dosyası
        every_n: Her N. kareyi işle (1 = tümü)
        scale: Çözünürlük ölçeği (1.0 = orijinal, 0.5 = yarı)
        out_path: Annotated video çıktı yolu (None = kaydetme)
        max_frames: İşlenecek maksimum kare sayısı
        show_display: OpenCV penceresi aç (sadece masaüstü)
        json_out: JSON çıktı dosyası
    """
    try:
        import cv2
    except ImportError:
        print("[HATA] opencv-python kurulu değil.")
        return {}

    # Pipeline yükle
    from ai.pipeline import Pipeline
    pipeline = Pipeline()
    print(f"[VideoTest] Dedektör: {pipeline.mode_name}")
    print(f"[VideoTest] LP Dedektör: {'Aktif' if pipeline.lp_detector.available else 'Yok (fallback)'}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[HATA] Video açılamadı: {video_path}")
        return {}

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out_w = max(1, int(src_w * scale))
    out_h = max(1, int(src_h * scale))

    print(f"[VideoTest] {os.path.basename(video_path)}")
    print(f"  Çözünürlük: {src_w}x{src_h} → işlem: {out_w}x{out_h}")
    print(f"  FPS: {src_fps:.1f}, Toplam kare: {total}, Her {every_n}. kare")

    writer = None
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_path, fourcc, src_fps / every_n, (out_w, out_h))

    results: List[dict] = []
    plates_found: List[str] = []
    swerving_count = 0
    frame_idx = 0
    processed = 0
    t_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        if frame_idx % every_n != 0:
            continue
        if max_frames and processed >= max_frames:
            break

        # Ölçekle
        if scale != 1.0:
            frame_proc = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
        else:
            frame_proc = frame

        is_critical = True  # Video test modunda daima kritik (plaka + sürücü)
        result, _ = pipeline.process(frame_proc, critical=is_critical, fps=src_fps)
        result_dict = result.model_dump()
        result_dict["frame_id"] = frame_idx
        results.append(result_dict)
        processed += 1

        plate_text = result.vehicle.plate.text
        if plate_text and plate_text not in plates_found:
            plates_found.append(plate_text)
            print(f"  [Kare {frame_idx}] Plaka tespit: {plate_text} "
                  f"(güven: {result.vehicle.plate.confidence:.0%})")

        if result.vehicle.swerving:
            swerving_count += 1
            if swerving_count == 1:
                print(f"  [Kare {frame_idx}] ⚠ SWERVING tespit edildi!")

        if result.risk.score >= 30:
            print(f"  [Kare {frame_idx}] Risk: {result.risk.score} [{result.risk.level}] "
                  f"— {', '.join(result.risk.factors)}")

        # Annotate
        annotated = annotate_frame(frame_proc, result_dict)

        if writer:
            writer.write(annotated)

        if show_display:
            cv2.imshow("Video Test — YZ", annotated)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

        if processed % 20 == 0:
            elapsed = time.time() - t_start
            fps_proc = processed / elapsed if elapsed > 0 else 0
            print(f"  İşlendi: {processed} kare ({fps_proc:.1f} kare/sn)")

    cap.release()
    if writer:
        writer.release()
    if show_display:
        cv2.destroyAllWindows()

    elapsed = time.time() - t_start
    summary = {
        "video": os.path.basename(video_path),
        "processed_frames": processed,
        "total_video_frames": total,
        "elapsed_s": round(elapsed, 2),
        "plates_found": plates_found,
        "swerving_frames": swerving_count,
        "output_video": out_path,
        "results_count": len(results),
    }

    print(f"\n{'='*50}")
    print(f"İşleme tamamlandı: {processed} kare / {elapsed:.1f} sn")
    print(f"Tespit edilen plakalar: {plates_found or 'yok'}")
    print(f"Swerving karesi: {swerving_count}")
    if out_path:
        print(f"Çıktı video: {out_path}")

    if json_out:
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "frames": results}, f, ensure_ascii=False, indent=2)
        print(f"JSON çıktı: {json_out}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Akıllı Yol Güvenliği — Video Test Aracı",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Örnekler:
  python tools/test_video.py project-files/test-verisi/video_3.mp4
  python tools/test_video.py video.mp4 --scale 0.5 --out output/result.mp4
  python tools/test_video.py video.mp4 --every 5 --json-out results.json
"""
    )
    parser.add_argument("video", help="Giriş video dosyası")
    parser.add_argument("--every", type=int, default=2, metavar="N",
                        help="Her N. kareyi işle (varsayılan: 2)")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Çözünürlük ölçeği 0.1-1.0 (varsayılan: 1.0)")
    parser.add_argument("--out", default=None, metavar="PATH",
                        help="Annotated video çıktı yolu (örn: output/result.mp4)")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="İşlenecek maksimum kare sayısı")
    parser.add_argument("--display", action="store_true",
                        help="OpenCV penceresi aç (masaüstü ortamı gerekli)")
    parser.add_argument("--json-out", default=None, metavar="PATH",
                        help="JSON çıktı dosyası")

    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"[HATA] Dosya bulunamadı: {args.video}")
        sys.exit(1)

    # Varsayılan çıktı yolu
    if args.out is None and not args.json_out:
        base = os.path.splitext(os.path.basename(args.video))[0]
        args.out = os.path.join("output", f"{base}_annotated.mp4")
        print(f"[VideoTest] Çıktı: {args.out}")

    process_video(
        video_path=args.video,
        every_n=args.every,
        scale=args.scale,
        out_path=args.out,
        max_frames=args.max_frames,
        show_display=args.display,
        json_out=args.json_out,
    )


if __name__ == "__main__":
    main()
