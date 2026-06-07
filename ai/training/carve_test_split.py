"""
Train'den held-out **test** bölmesi ayırır (dürüst nihai metrik için).

Neden var: Veri seti `train`/`val` ile geldi; `val` erken-durdurma (patience) için
kullanıldığından model dolaylı olarak val'e göre seçilir → val mAP hafif iyimser.
Gerçek genelleme için modelin EĞİTİMDE HİÇ görmediği ayrı bir `test` bölmesi gerekir
(plan: dürüst değerlendirme). Bu betik train'den seed'li rastgele bir alt-küme seçip
görüntü+etiket çiftini `test/`'e TAŞIR ve bir **manifest** yazar (geri alınabilir).

Tasarım:
  - Deterministik (seed=42) → tekrarlanabilir, takım aynı bölmeyi üretir.
  - Görüntü ve etiket BİRLİKTE taşınır (eşleşmeyen varsa atlanır, raporlanır).
  - `manifest.json`'a taşınan dosyalar yazılır → `--undo` ile geri alınır (sızıntı/hatada).
  - Çevrimdışı, GPU/ağ gerekmez.

Kullanım:
  python -m ai.training.carve_test_split --n 1000           # 1000 çift train->test
  python -m ai.training.carve_test_split --undo             # son taşımayı geri al
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DS = os.path.join(ROOT, "datasets", "yolguvenligi")
MANIFEST = os.path.join(DS, "test_split_manifest.json")


def _pairs(split: str):
    """split içindeki (stem -> (img_path, label_path)) eşleşmelerini döner."""
    img_dir = os.path.join(DS, "images", split)
    lbl_dir = os.path.join(DS, "labels", split)
    out = {}
    for fn in os.listdir(img_dir):
        stem, ext = os.path.splitext(fn)
        if ext.lower() != ".jpg":
            continue
        lbl = os.path.join(lbl_dir, stem + ".txt")
        if os.path.exists(lbl):
            out[stem] = (os.path.join(img_dir, fn), lbl)
    return out


def carve(n: int, seed: int) -> None:
    if os.path.exists(MANIFEST):
        sys.exit(f"HATA: {MANIFEST} zaten var → önce --undo ile geri al. Çift taşıma yok.")
    for split in ("test",):
        os.makedirs(os.path.join(DS, "images", split), exist_ok=True)
        os.makedirs(os.path.join(DS, "labels", split), exist_ok=True)

    train = _pairs("train")
    stems = sorted(train)                       # deterministik taban
    random.Random(seed).shuffle(stems)
    chosen = stems[:n]
    moved = []
    for stem in chosen:
        img, lbl = train[stem]
        dst_img = os.path.join(DS, "images", "test", os.path.basename(img))
        dst_lbl = os.path.join(DS, "labels", "test", os.path.basename(lbl))
        shutil.move(img, dst_img)
        shutil.move(lbl, dst_lbl)
        moved.append(stem)

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump({"seed": seed, "n": len(moved), "stems": moved}, f, indent=2)

    print(f"Taşındı: {len(moved)} çift train -> test (seed={seed})")
    print(f"Kalan train: {len(train) - len(moved)} | test: {len(moved)}")
    print(f"Manifest: {MANIFEST}")


def undo() -> None:
    if not os.path.exists(MANIFEST):
        sys.exit("HATA: manifest yok → geri alınacak taşıma bulunamadı.")
    with open(MANIFEST, encoding="utf-8") as f:
        man = json.load(f)
    back = 0
    for stem in man["stems"]:
        img = os.path.join(DS, "images", "test", stem + ".jpg")
        lbl = os.path.join(DS, "labels", "test", stem + ".txt")
        if os.path.exists(img):
            shutil.move(img, os.path.join(DS, "images", "train", stem + ".jpg"))
        if os.path.exists(lbl):
            shutil.move(lbl, os.path.join(DS, "labels", "train", stem + ".txt"))
        back += 1
    os.remove(MANIFEST)
    print(f"Geri alındı: {back} çift test -> train. Manifest silindi.")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Train'den held-out test bölmesi ayır")
    ap.add_argument("--n", type=int, default=1000, help="test'e taşınacak çift sayısı")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--undo", action="store_true", help="son taşımayı geri al")
    args = ap.parse_args()
    if args.undo:
        undo()
    else:
        carve(args.n, args.seed)


if __name__ == "__main__":
    main()
