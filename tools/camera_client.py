"""
Masaüstü kamera istemcisi (alternatif ingest yolu) — OpenCV + WebSocket.

Tarayıcı yerine doğrudan Python'dan kamera akışı gönderir. macOS'ta Mac dahili
kamerayı veya **iPhone Continuity Camera**'yı (normal kamera cihazı olarak görünür)
kullanabilir. Backend çalışırken:

  python -m tools.camera_client --source 0 --fps 7
  python -m tools.camera_client --source 1            # iPhone Continuity (genelde index 1)
  python -m tools.camera_client --source video.mp4    # dosyadan test

Gelen FrameResult terminale özet olarak basılır; pencere açılabiliyorsa overlay çizilir.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time

import cv2

try:
    import websockets
except ImportError:
    raise SystemExit("websockets gerekli: pip install websockets")


def draw_overlay(frame, data):
    for d in data.get("detections", []):
        b = d["bbox"]
        color = (255, 123, 47) if d["label"] == "vehicle" else (
            (94, 77, 255) if d["label"] == "phone" else (113, 204, 46))
        cv2.rectangle(frame, (int(b["x1"]), int(b["y1"])), (int(b["x2"]), int(b["y2"])), color, 2)
        cv2.putText(frame, f"{d['label']} {int(d['confidence']*100)}%",
                    (int(b["x1"]), int(b["y1"]) - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
    mode = data.get("mode", "NORMAL")
    col = (94, 77, 255) if mode == "CRITICAL" else (113, 204, 46)
    cv2.putText(frame, f"{mode}  bant:{data['qod']['bandwidth_mbps']}Mbps  risk:{data['risk']['score']}",
                (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
    return frame


async def run(source, url, fps, show):
    cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
    if not cap.isOpened():
        raise SystemExit(f"Kamera/kaynak açılamadı: {source}")
    delay = 1.0 / fps
    async with websockets.connect(url, max_size=None) as ws:
        print(f"Bağlandı: {url} | kaynak: {source} | çıkış için Ctrl+C")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            small = cv2.resize(frame, (640, int(640 * frame.shape[0] / frame.shape[1])))
            ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 60])
            data_url = "data:image/jpeg;base64," + base64.b64encode(buf).decode()
            # §12-P1: yakalama anı damgası — hız Δt'si ağ jitter'ından bağımsız olsun
            await ws.send(json.dumps({"frame": data_url, "client_ts": time.time()}))
            resp = json.loads(await ws.recv())
            if "error" not in resp:
                v = resp["vehicle"]
                print(f"\r[{resp['mode']:8}] araç:{v['present']} plaka:{v['plate']['text'] or '-':10} "
                      f"hız:{v['speed_kmh']} risk:{resp['risk']['score']:3} "
                      f"bant:{resp['qod']['bandwidth_mbps']}Mbps fps:{resp['fps']}   ", end="", flush=True)
                if show:
                    cv2.imshow("Yol Guvenligi", draw_overlay(small, resp))
                    if cv2.waitKey(1) & 0xFF == 27:
                        break
            await asyncio.sleep(delay)
    cap.release()
    if show:
        cv2.destroyAllWindows()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0", help="kamera index (0=Mac, 1=iPhone) veya video yolu")
    ap.add_argument("--host", default="localhost:8000")
    ap.add_argument("--fps", type=float, default=7)
    ap.add_argument("--no-window", action="store_true", help="görüntü penceresi açma")
    args = ap.parse_args()
    url = f"ws://{args.host}/ws/ingest"
    try:
        asyncio.run(run(args.source, url, args.fps, show=not args.no_window))
    except KeyboardInterrupt:
        print("\nDurduruldu.")


if __name__ == "__main__":
    main()
