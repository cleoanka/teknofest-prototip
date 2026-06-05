"""
Gerçek-mod pipeline duman testi (AI_MODE=real) — plan Faz 3 doğrulaması.

Ne yapar: Gerçek YOLOv8'i `Pipeline.process()`'ten geçirir ve hangi bileşenin
**gerçek mi mock mu** çözüldüğünü + üretilen tespitleri yazar. Amaç: ortam
değiştikten sonra (torch/ultralytics kurulumu) gerçek hattın uçtan uca çökmeden
çalıştığını tek komutla doğrulamak.

Neden otomatik teste dahil DEĞİL: gerçek model indirme + GPU ister; mock testleri
her ortamda yeşil kalsın diye (K4) bu betik elle çalıştırılır. Kütüphane (easyocr/
mediapipe) yoksa ilgili modül mock'a düşmeli, sistem çökmemeli — bu betik onu gösterir.

Kullanım:
  AI_MODE=real python -m eval.real_smoke
  AI_MODE=real python -m eval.real_smoke --image yol/kare.jpg
"""
from __future__ import annotations

import argparse
import os


def load_sample(path: str | None):
    """Verilen görüntüyü ya da (yoksa) ultralytics örnek 'bus.jpg'sini yükler."""
    import cv2
    if path:
        img = cv2.imread(path)
        if img is None:
            raise SystemExit(f"görüntü okunamadı: {path}")
        return img, path
    from ultralytics.utils import ASSETS   # örnek varlık (otobüs + insanlar)
    p = str(ASSETS / "bus.jpg")
    return cv2.imread(p), p


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows konsolu (cp1254) için (R1)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Gerçek-mod pipeline duman testi")
    ap.add_argument("--image", default=None, help="test görüntüsü (boşsa örnek bus.jpg)")
    args = ap.parse_args()

    # AI_MODE değerini erkenden oku (lru_cache'i temizle ki ortam değişikliği görülsün).
    from config.settings import get_settings
    get_settings.cache_clear()
    mode = get_settings().ai_mode
    print(f"AI_MODE = {mode}")

    img, path = load_sample(args.image)
    print("görüntü:", path, "| boyut:", None if img is None else img.shape)

    from ai.pipeline import Pipeline
    from ai.detector import YoloDetector
    pipe = Pipeline()
    print("detector :", type(pipe.detector).__name__,
          "(gerçek YOLO mu?:", isinstance(pipe.detector, YoloDetector), ")")
    print("plate    :", pipe.plate_reader.mode)
    print("driver   :", pipe.driver.mode)

    for crit in (False, True):
        res, ctx = pipe.process(img, critical=crit)
        labels = sorted({d.label for d in res.detections})
        print(f"\n--- {'KRİTİK' if crit else 'NORMAL'} ---")
        print(" mode:", res.mode, "| model_profile:", res.model_profile)
        print(" tespitler:", labels, f"({len(res.detections)} kutu)")
        print(" araç:", res.vehicle.present, "| vtype:", res.vehicle.vtype,
              "| conf:", round(ctx.vehicle_conf, 3), "| renk:", res.vehicle.color)
        print(" plaka:", res.vehicle.plate.text, "| risk:", res.risk)

    reason = os.environ.get("AI_FALLBACK_REASON")
    if reason:
        print("\nDETECTOR FALLBACK:", reason)
    print("\nÇÖKMEDİ ✓")


if __name__ == "__main__":
    main()
