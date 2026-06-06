"""
COCO val2017 → birleşik YOLO alt-kümesi (train/val) oluşturucu (plan.md Bölüm 5).

Neden var: `prepare_dataset.coco` yalnız **etiket** yazar ve tek bir split üretir.
Gerçek bir `best.pt v0` için bize hazır bir train/val bölünmesi + imajların doğru
klasöre kopyalanması gerekiyor. Bu yardımcı:

  1) COCO instances JSON'ını okur,
  2) yalnız hedef sınıf (vehicle/person/phone) içeren imajları tutar
     (+ küçük bir negatif/arka-plan oranı, robustluk için),
  3) imajları id'ye göre sıralayıp deterministik biçimde train/val'a böler,
  4) her split için `coco_to_yolo` ile etiketleri yazar (ai/training/prepare_dataset),
  5) eşleşen imajları images/<split> altına kopyalar.

Tasarım (K4): saf dönüştürme mantığı prepare_dataset'ten yeniden kullanılır; bu modül
yalnız bölme + IO (kopyalama) ekler. Tek seferlik veri kurulumu içindir.

Kullanım:
  python -m ai.training.build_coco_subset \
      --json datasets/raw/coco/annotations/instances_val2017.json \
      --images datasets/raw/coco/val2017 \
      --out datasets/yolguvenligi \
      --val-frac 0.2 --neg-frac 0.1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from typing import Dict, List

from config.settings import COCO_TO_TARGET, TARGET_CLASSES
from ai.training.prepare_dataset import coco_to_yolo, write_yolo_labels


def _target_category_ids(coco: dict) -> set:
    """Hedef sınıflara eşlenebilen COCO category_id kümesi."""
    name_to_idx = {n: i for i, n in enumerate(TARGET_CLASSES)}
    ok = set()
    for cat in coco.get("categories", []):
        if COCO_TO_TARGET.get(cat.get("name")) in name_to_idx:
            ok.add(cat["id"])
    return ok


def _split_images(images: List[dict], pos_ids: set, val_frac: float, neg_frac: float):
    """İmaj listesini (pozitif + örneklenmiş negatif) train/val'a böler.

    Deterministik: id'ye göre sırala; negatifleri 1/neg_frac adımıyla örnekle;
    kalan listede her 1/val_frac'inci imaj val'a gider.
    """
    pos = [im for im in images if im["id"] in pos_ids]
    neg = [im for im in images if im["id"] not in pos_ids]
    pos.sort(key=lambda im: im["id"])
    neg.sort(key=lambda im: im["id"])

    if neg_frac > 0:
        step_neg = max(1, round(1.0 / neg_frac))
        kept_neg = neg[::step_neg]
    else:
        kept_neg = []

    kept = sorted(pos + kept_neg, key=lambda im: im["id"])
    step_val = max(2, round(1.0 / val_frac))
    splits: Dict[str, List[dict]] = {"train": [], "val": []}
    for i, im in enumerate(kept):
        splits["val" if i % step_val == 0 else "train"].append(im)
    return splits, len(pos), len(kept_neg)


def build(coco_json: str, images_src: str, out_root: str,
          val_frac: float = 0.2, neg_frac: float = 0.1) -> dict:
    with open(coco_json, "r", encoding="utf-8") as f:
        coco = json.load(f)

    cat_ok = _target_category_ids(coco)
    pos_ids = {ann["image_id"] for ann in coco.get("annotations", [])
               if ann.get("category_id") in cat_ok}

    splits, n_pos, n_neg = _split_images(coco["images"], pos_ids, val_frac, neg_frac)
    print(f"Süzme: {n_pos} pozitif imaj (hedef sınıf içeren) + {n_neg} negatif (örneklenmiş)")

    # annotation'ları image_id'ye göre indeksle (her split için alt-coco kurmak için)
    anns_by_img: Dict[int, List[dict]] = {}
    for ann in coco.get("annotations", []):
        anns_by_img.setdefault(ann["image_id"], []).append(ann)

    stats = {"per_split": {}, "per_class": Counter(), "copied": 0, "missing_images": 0}
    for split, imgs in splits.items():
        sub = {
            "images": imgs,
            "annotations": [a for im in imgs for a in anns_by_img.get(im["id"], [])],
            "categories": coco.get("categories", []),
        }
        boxes_by_file, class_counts, skipped = coco_to_yolo(sub)
        labels_dir = os.path.join(out_root, "labels", split)
        written = write_yolo_labels(boxes_by_file, labels_dir)

        # imajları kopyala (etiket stem'i ile eşleşmeli)
        img_dir = os.path.join(out_root, "images", split)
        os.makedirs(img_dir, exist_ok=True)
        copied = 0
        for im in imgs:
            src = os.path.join(images_src, im["file_name"])
            if not os.path.isfile(src):
                stats["missing_images"] += 1
                continue
            shutil.copy2(src, os.path.join(img_dir, os.path.basename(im["file_name"])))
            copied += 1

        stats["per_split"][split] = {
            "images": len(imgs), "labels": written, "copied": copied,
            "boxes": int(sum(class_counts.values())),
        }
        stats["per_class"].update(class_counts)
        stats["copied"] += copied
        print(f"  {split:5s} | imaj {len(imgs):5d} | etiket {written:5d} | "
              f"kopyalandı {copied:5d} | kutu {int(sum(class_counts.values())):6d}")

    print("Sınıf dağılımı:")
    for name in TARGET_CLASSES:
        print(f"  {name:14s} {stats['per_class'].get(name, 0)}")
    if stats["missing_images"]:
        print(f"⚠ {stats['missing_images']} imaj kaynak klasörde bulunamadı (atlandı).")
    return stats


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="COCO → birleşik YOLO alt-kümesi (train/val)")
    ap.add_argument("--json", required=True, help="COCO instances .json")
    ap.add_argument("--images", required=True, help="COCO imaj klasörü (örn. val2017)")
    ap.add_argument("--out", default="datasets/yolguvenligi", help="birleşik küme kökü")
    ap.add_argument("--val-frac", type=float, default=0.2, help="val oranı (varsayılan 0.2)")
    ap.add_argument("--neg-frac", type=float, default=0.1,
                    help="tutulacak negatif/arka-plan oranı (varsayılan 0.1)")
    args = ap.parse_args()
    build(args.json, args.images, args.out, args.val_frac, args.neg_frac)


if __name__ == "__main__":
    main()
