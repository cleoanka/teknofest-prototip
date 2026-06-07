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

# Renk tanımları — Supervision sv.Color (RGB). Eski cv2/BGR sabitlerinin RGB karşılığı.
_SV_PALETTE = {
    "vehicle":   (0, 200, 0),      # Yeşil — araç kutusu
    "swerving":  (220, 0, 0),      # Kırmızı — swerving uyarısı (araç kutusu rengini değiştirir)
    "plate":     (255, 220, 0),    # Sarı — plaka kutusu
    "driver":    (0, 120, 255),    # Mavi — sürücü ROI
    "passenger": (255, 120, 0),    # Turuncu — yolcu ROI
    "person":    (255, 255, 255),  # Beyaz — kişi tespiti
    "phone":     (255, 0, 0),      # Kırmızı — telefon
}


def _xyxy(bbox: dict):
    return np.array([[bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]]], dtype=float)


class FrameAnnotator:
    """Supervision tabanlı kare çizimi — sv.BoxAnnotator/LabelAnnotator/TraceAnnotator.

    Eski el-yapımı cv2.rectangle/putText (`draw_box`) yerine; kategori başına sabit
    renkli annotator çiftleri. Araç yörüngesi sv.TraceAnnotator ile BOTTOM_CENTER
    (= bbox alt-orta, "foot point") konumundan çizilir — BEV/homografi hız hesabının
    izlediği nokta ile aynı, böylece çizilen iz gerçek hız hesabını görselleştirir.

    NOT: Risk paneli ve kare-bilgisi HUD'ı serbest-biçimli paneller olduğundan
    (sv'nin kutu/etiket modeline uymaz) cv2 ile çizilmeye devam eder — annotasyon
    değil, özel dashboard öğeleridir.

    Video boyunca TEK instance kullanılmalı: TraceAnnotator iz geçmişini saklar;
    her kare için yeniden oluşturmak izi sıfırlar.
    """

    def __init__(self):
        import supervision as sv
        self._sv = sv
        colors = {k: sv.Color(r=r, g=g, b=b) for k, (r, g, b) in _SV_PALETTE.items()}
        self._box = {
            k: sv.BoxAnnotator(color=c, thickness=3 if k in ("vehicle", "swerving") else 2,
                               color_lookup=sv.ColorLookup.INDEX)
            for k, c in colors.items()
        }
        self._label = {
            k: sv.LabelAnnotator(color=c, text_color=sv.Color.BLACK,
                                 text_scale=0.5, text_thickness=1, text_padding=4,
                                 color_lookup=sv.ColorLookup.INDEX)
            for k, c in colors.items()
        }
        self._trace = sv.TraceAnnotator(color=colors["vehicle"], thickness=2,
                                         trace_length=40, position=sv.Position.BOTTOM_CENTER,
                                         color_lookup=sv.ColorLookup.INDEX)

    def _detection(self, bbox: dict, confidence: float = 1.0, tracker_id=None):
        kw = {"xyxy": _xyxy(bbox), "confidence": np.array([confidence], dtype=float)}
        if tracker_id is not None:
            kw["tracker_id"] = np.array([int(tracker_id)], dtype=int)
        return self._sv.Detections(**kw)

    def _box_label(self, scene, key: str, bbox: dict, label: str, tracker_id=None):
        det = self._detection(bbox, tracker_id=tracker_id)
        scene = self._box[key].annotate(scene, det)
        scene = self._label[key].annotate(scene, det, labels=[label])
        return scene, det

    def annotate(self, frame: np.ndarray, result_dict: dict) -> np.ndarray:
        """FrameResult dict'inden alınan sonuçları kareye çiz."""
        scene = frame.copy()
        vehicle = result_dict.get("vehicle", {})
        driver_state = result_dict.get("driver", {})
        risk = result_dict.get("risk", {})

        # Araç kutusu + etiket + yörünge (foot point izi — homografi ile aynı nokta)
        vbbox = vehicle.get("bbox")
        if vbbox:
            tid = vehicle.get("track_id")
            swerving = vehicle.get("swerving", False)
            key = "swerving" if swerving else "vehicle"
            label_parts = [vehicle.get("vtype") or "araç"]
            plate_text = vehicle.get("plate", {}).get("text")
            if plate_text:
                label_parts.append(plate_text)
            speed = vehicle.get("speed_kmh")
            if speed is not None:
                tag = "" if vehicle.get("speed_is_calibrated") else "~"   # ~ = kalibrasyonsuz tahmin
                label_parts.append(f"{tag}{speed} km/h")
            if swerving:
                label_parts.append("⚠ SWERVING")
            scene, det = self._box_label(scene, key, vbbox, " | ".join(label_parts), tracker_id=tid)
            if tid is not None:
                scene = self._trace.annotate(scene, det)

        # Plaka kutusu (sarı)
        pbbox = vehicle.get("plate_bbox")
        if pbbox:
            plate_text = vehicle.get("plate", {}).get("text") or "?"
            scene, _ = self._box_label(scene, "plate", pbbox, f"PLAKA: {plate_text}")

        # Sürücü ROI (mavi)
        dbbox = vehicle.get("driver_bbox")
        if dbbox:
            phone_label = " [TELEFON!]" if driver_state.get("phone_use") else ""
            scene, _ = self._box_label(scene, "driver", dbbox, f"SÜRÜCÜ{phone_label}")

        # Yolcu ROI (turuncu)
        psbbox = vehicle.get("passenger_bbox")
        if psbbox:
            pax_phone = " [telefon]" if driver_state.get("passenger_phone") else ""
            scene, _ = self._box_label(scene, "passenger", psbbox, f"YOLCU{pax_phone}")

        # Tespit edilen nesneler (kişi, telefon)
        for det in result_dict.get("detections", []):
            lbl = det.get("label", "")
            bb = det.get("bbox", {})
            if lbl == "phone":
                scene, _ = self._box_label(scene, "phone", bb, f"telefon {det.get('confidence', 0):.0%}")
            elif lbl == "person":
                scene, _ = self._box_label(scene, "person", bb, f"kişi {det.get('confidence', 0):.0%}")

        return self._draw_hud(scene, result_dict, risk, vehicle)

    @staticmethod
    def _draw_hud(scene, result_dict, risk, vehicle):
        """Risk paneli + kare bilgisi — serbest-biçimli HUD, cv2 ile (annotasyon değil)."""
        import cv2
        h, w = scene.shape[:2]
        score = risk.get("score", 0)
        level = risk.get("level", "LOW")
        factors = ", ".join(risk.get("factors", []))
        risk_color = (0, 0, 200) if score >= 85 else (0, 128, 255) if score >= 60 \
            else (0, 200, 255) if score >= 30 else (0, 200, 0)
        cv2.rectangle(scene, (w - 260, 10), (w - 10, 90), (20, 20, 20), -1)
        cv2.putText(scene, f"Risk: {score}/100 [{level}]", (w - 250, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, risk_color, 1, cv2.LINE_AA)
        if factors:
            cv2.putText(scene, factors[:35], (w - 250, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (200, 200, 200), 1, cv2.LINE_AA)

        frame_id = result_dict.get("frame_id", 0)
        latency = result_dict.get("latency_ms", 0)
        plate_text = vehicle.get("plate", {}).get("text") or ""
        info = f"Kare #{frame_id} | {latency:.0f}ms"
        if plate_text:
            info += f" | {plate_text}"
        cv2.putText(scene, info, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1, cv2.LINE_AA)
        return scene


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
    try:
        annotator = FrameAnnotator()
    except ImportError:
        print("[HATA] supervision kurulu değil — `pip install supervision` gerekir.")
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
        # Aşama 0 — video-zaman çizgisi damgası: önce gerçek PTS (VFR'yi de doğru
        # ele alır), yoksa indeks/fps (CFR). Wall-clock İŞLEME süresi DEĞİL — kareler
        # arası gerçek video süresi hız Δt'sine girsin diye.
        pts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        if pts_ms and pts_ms > 0:
            frame_ts = pts_ms / 1000.0
        elif src_fps > 0:
            frame_ts = frame_idx / src_fps
        else:
            frame_ts = None
        result, _ = pipeline.process(frame_proc, critical=is_critical,
                                     fps=src_fps, frame_ts=frame_ts)
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

        # Annotate (Supervision: BoxAnnotator/LabelAnnotator/TraceAnnotator)
        annotated = annotator.annotate(frame_proc, result_dict)

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
