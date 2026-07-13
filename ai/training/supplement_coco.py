"""
COCO train2017'den HEDEF SINIF içeren imajları indirip birleşik kümeye ekler (takviye).

Neden var: val2017 alt-kümesi bazı sınıflarda zayıf (truck 415, phone 262 kutu). train2017
(118k imaj) bu sınıflarda çok daha zengin (truck ~10k, phone ~6.4k kutu). Bu modül
**yalnız hedef sınıfı içeren** imajları seçer (tümünü değil), COCO image sunucusundan
**eşzamanlı** indirir, bizim taksonomiye (COCO_TO_TARGET) çevirir ve mevcut kümenin
**train** split'ine EKLER. val split'e dokunmaz (val2017 ≠ train2017 → sızıntı yok;
COCO imaj id/dosya adları iki split arasında ayrıktır).

Seçilen imajlardaki TÜM hedef sınıflar etiketlenir (bir truck imajındaki car/person da) →
genel veri de zenginleşir.

Kullanım:
  python -m ai.training.supplement_coco \
      --json datasets/raw/coco/annotations/instances_train2017.json \
      --out datasets/yolguvenligi --focus truck "cell phone" \
      --cap-per-class 0   # 0 = sınırsız (hepsi)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Set

from config.settings import TARGET_CLASSES
from ai.training.prepare_dataset import coco_to_yolo, write_yolo_labels

COCO_IMG_URL = "http://images.cocodataset.org/train2017/{}"


def select_image_ids(coco: dict, focus: List[str], cap_per_class: int = 0) -> Set[int]:
    """Hedef (focus) COCO sınıflarından en az birini içeren image_id kümesi.

    cap_per_class>0 ise her focus sınıfı için ilk N imaj (id-sıralı, deterministik).
    """
    name2id = {c["name"]: c["id"] for c in coco.get("categories", [])}
    focus_ids = {name2id[n]: n for n in focus if n in name2id}
    per_class: Dict[str, List[int]] = {n: [] for n in focus}
    seen_pair: Set = set()
    for ann in coco.get("annotations", []):
        n = focus_ids.get(ann.get("category_id"))
        if n is not None:
            key = (n, ann["image_id"])
            if key not in seen_pair:
                seen_pair.add(key)
                per_class[n].append(ann["image_id"])
    selected: Set[int] = set()
    for n in focus:
        ids = sorted(per_class[n])              # deterministik
        if cap_per_class and cap_per_class > 0:
            ids = ids[:cap_per_class]
        selected.update(ids)
    return selected


def download_images(images_meta: List[dict], out_dir: str, workers: int = 16,
                    timeout: float = 20.0, retries: int = 3) -> int:
    """İmajları COCO sunucusundan eşzamanlı indirir (zaten varsa atlar). Başarılı sayısını döner.

    Sağlamlık: per-istek timeout (takılan worker'ı keser), N denemeli retry (artan bekleme),
    tarayıcı User-Agent'i (bazı sunucular varsayılan urllib UA'yı reddeder). Düşük worker
    sayısı sunucu hız-kısıtlamasını (throttle) azaltır.
    """
    os.makedirs(out_dir, exist_ok=True)

    def fetch(im: dict) -> bool:
        fn = im["file_name"]
        dst = os.path.join(out_dir, fn)
        if os.path.isfile(dst) and os.path.getsize(dst) > 0:
            return True
        url = im.get("coco_url") or COCO_IMG_URL.format(fn)
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r, open(dst, "wb") as out:
                    shutil.copyfileobj(r, out)
                if os.path.getsize(dst) > 0:
                    return True
            except Exception:
                if os.path.exists(dst):
                    try:
                        os.remove(dst)
                    except OSError:
                        pass
                time.sleep(0.5 * (attempt + 1))   # artan bekleme (throttle'a nazik)
        return False

    ok = done = 0
    total = len(images_meta)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(fetch, im) for im in images_meta]
        for f in as_completed(futs):
            done += 1
            if f.result():
                ok += 1
            if done % 500 == 0 or done == total:
                print(f"  indirildi {done}/{total} (başarılı {ok})", flush=True)
    return ok


def supplement(json_path: str, out_root: str, focus: List[str],
               cap_per_class: int = 0, workers: int = 16,
               timeout: float = 20.0, retries: int = 3) -> dict:
    print(f"train2017 json yükleniyor: {json_path}", flush=True)
    with open(json_path, "r", encoding="utf-8") as f:
        coco = json.load(f)

    sel_ids = select_image_ids(coco, focus, cap_per_class)
    images_meta = [im for im in coco["images"] if im["id"] in sel_ids]
    print(f"Seçilen imaj ({', '.join(focus)} içeren): {len(images_meta)}", flush=True)

    img_dir = os.path.join(out_root, "images", "train")
    lbl_dir = os.path.join(out_root, "labels", "train")
    print(f"İndiriliyor → {img_dir} ...", flush=True)
    ok = download_images(images_meta, img_dir, workers, timeout, retries)
    print(f"İndirme bitti: {ok}/{len(images_meta)} başarılı", flush=True)

    # Yalnız başarıyla inen imajlar için etiket yaz (diskte var olanlar).
    present = [im for im in images_meta
               if os.path.isfile(os.path.join(img_dir, im["file_name"]))]
    sub = {
        "images": present,
        "annotations": [a for a in coco["annotations"] if a["image_id"] in sel_ids],
        "categories": coco.get("categories", []),
    }
    boxes_by_file, class_counts, _ = coco_to_yolo(sub)
    written = write_yolo_labels(boxes_by_file, lbl_dir)
    print(f"Etiket yazıldı: {written} dosya → {lbl_dir}", flush=True)
    print("Eklenen kutu dağılımı:", flush=True)
    for name in TARGET_CLASSES:
        if class_counts.get(name):
            print(f"  {name:14s} +{class_counts[name]}", flush=True)
    return {"selected": len(images_meta), "downloaded": ok, "labels": written,
            "added_boxes": dict(class_counts)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="train2017 hedef-sınıf takviyesi (indir+birleştir)")
    ap.add_argument("--json", required=True, help="COCO instances_train2017.json")
    ap.add_argument("--out", default="datasets/yolguvenligi", help="birleşik küme kökü")
    ap.add_argument("--focus", nargs="+", default=["truck", "cell phone"],
                    help="hedef COCO sınıf adları (içeren imajlar indirilir)")
    ap.add_argument("--cap-per-class", type=int, default=0, help="sınıf başına imaj sınırı (0=sınırsız)")
    ap.add_argument("--workers", type=int, default=16, help="eşzamanlı indirme sayısı (düşük=throttle az)")
    ap.add_argument("--timeout", type=float, default=20.0, help="per-istek timeout (s)")
    ap.add_argument("--retries", type=int, default=3, help="başarısız indirme deneme sayısı")
    args = ap.parse_args()
    supplement(args.json, args.out, args.focus, args.cap_per_class,
               args.workers, args.timeout, args.retries)


if __name__ == "__main__":
    main()
