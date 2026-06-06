"""
Veri kümesi hazırlama yardımcıları (plan.md Bölüm 5 — "Veri Hazırlama Hattı").

Neden var: Elimizde etiketli saha verisi yok; strateji sıfır etiketten büyük açık
kaynak havuzuna (COCO/BDD100K/CCPD) dayanıyor (plan.md Bölüm 4). Bu modül o havuzu
**tek birleşik YOLO formatına** çevirmek ve kümeyi commit/eğitim öncesi **denetlemek**
için gereken yazılım parçalarını sağlar. Tümü çevrimdışı ve GPU'suz çalışır
(ultralytics gerekmez) — böylece testler her ortamda yeşil kalır (K4).

Yetenekler:
  1) frames   — videodan kare çıkar (komite senaryo videoları için).
  2) scaffold — YOLO klasör iskeleti oluştur.
  3) coco     — COCO instances JSON'ını birleşik YOLO etiketlerine çevir
                (sınıf eşleme config/settings.py:COCO_TO_CANONICAL ile).
  4) audit    — birleşik kümeyi denetle: sınıf başına kutu sayımı, etiket format
                doğrulama, train/val/test sızıntısı, yetim görüntü/etiket.
  5) verify   — data.yaml sınıfları config/settings.py:TARGET_CLASSES ile birebir mi?

Kullanım:
  python -m ai.training.prepare_dataset frames   --video ornek.mp4 --out datasets/raw --fps 2
  python -m ai.training.prepare_dataset scaffold --root datasets/yolguvenligi
  python -m ai.training.prepare_dataset coco     --json instances.json --out datasets/yolguvenligi --split train
  python -m ai.training.prepare_dataset audit    --root datasets/yolguvenligi
  python -m ai.training.prepare_dataset verify    --data ai/training/data.yaml
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from typing import Dict, List, Optional, Tuple

from config.settings import TARGET_CLASSES, COCO_TO_TARGET

# Kabul edilen görüntü uzantıları (görüntü↔etiket eşleştirmede kullanılır).
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# Tek bir YOLO kutusu: (sınıf_idx, x_merkez, y_merkez, genişlik, yükseklik) — 0-1 normalize.
YoloBox = Tuple[int, float, float, float, float]


# ──────────────────────────────────────────────────────────────────────────────
# 1) Videodan kare çıkarma
# ──────────────────────────────────────────────────────────────────────────────
def extract_frames(video: str, out: str, fps: float = 2.0) -> int:
    import cv2
    os.makedirs(out, exist_ok=True)
    cap = cv2.VideoCapture(video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # Kaynak fps'i hedef fps'e indirgemek için kaç karede bir alınacağı.
    step = max(1, int(round(src_fps / fps)))
    i, saved = 0, 0
    base = os.path.splitext(os.path.basename(video))[0]
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            cv2.imwrite(os.path.join(out, f"{base}_{saved:05d}.jpg"), frame)
            saved += 1
        i += 1
    cap.release()
    print(f"{saved} kare çıkarıldı -> {out}")
    return saved


# ──────────────────────────────────────────────────────────────────────────────
# 2) YOLO klasör iskeleti
# ──────────────────────────────────────────────────────────────────────────────
def scaffold(root: str) -> None:
    for split in ("train", "val", "test"):
        os.makedirs(os.path.join(root, "images", split), exist_ok=True)
        os.makedirs(os.path.join(root, "labels", split), exist_ok=True)
    print(f"YOLO iskeleti hazır -> {root}")
    print("Etiketleme: labelImg / Roboflow / CVAT ile YOLO formatında etiketle.")


# ──────────────────────────────────────────────────────────────────────────────
# 3) COCO -> birleşik YOLO dönüştürme (plan.md Bölüm 5, adım 1-2)
# ──────────────────────────────────────────────────────────────────────────────
def _clamp01(v: float) -> float:
    # YOLO koordinatları [0,1] dışına taşamaz (kenardaki kutular için güvenlik).
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def coco_to_yolo(
    coco: dict,
    class_map: Optional[Dict[str, str]] = None,
    target_classes: Optional[List[str]] = None,
) -> Tuple[Dict[str, List[YoloBox]], Counter, int]:
    """COCO instances sözlüğünü dosya-bazlı YOLO kutularına çevirir (saf fonksiyon, IO yok).

    Eşleme zinciri: COCO kategori adı → TARGET adı (class_map) → indeks (target_classes).
    Haritada olmayan veya hedef sınıflarda bulunmayan kategoriler **atlanır** (geçersiz
    sınıf üretmektense kutuyu düşürmek daha güvenli — birleşik şema bozulmaz).

    Dönüş: (dosya_adı -> [YoloBox...], sınıf_adı sayacı, atlanan_kutu_sayısı)
    """
    class_map = class_map if class_map is not None else COCO_TO_TARGET
    target_classes = target_classes if target_classes is not None else TARGET_CLASSES
    name_to_idx = {name: i for i, name in enumerate(target_classes)}

    # category_id -> hedef indeks (yalnız eşlenebilenler)
    cat_id_to_idx: Dict[int, int] = {}
    for cat in coco.get("categories", []):
        canonical = class_map.get(cat.get("name"))
        if canonical in name_to_idx:
            cat_id_to_idx[cat["id"]] = name_to_idx[canonical]

    # image_id -> (dosya_adı, genişlik, yükseklik)
    images: Dict[int, Tuple[str, float, float]] = {}
    for im in coco.get("images", []):
        images[im["id"]] = (im["file_name"], float(im["width"]), float(im["height"]))

    out: Dict[str, List[YoloBox]] = {fn: [] for (fn, _, _) in images.values()}
    class_counts: Counter = Counter()
    skipped = 0

    for ann in coco.get("annotations", []):
        idx = cat_id_to_idx.get(ann.get("category_id"))
        img = images.get(ann.get("image_id"))
        if idx is None or img is None:
            skipped += 1
            continue
        file_name, iw, ih = img
        if iw <= 0 or ih <= 0:
            skipped += 1
            continue
        # COCO bbox = [x_min, y_min, w, h] (piksel) → YOLO merkez-normalize.
        x, y, w, h = ann["bbox"]
        xc = _clamp01((x + w / 2.0) / iw)
        yc = _clamp01((y + h / 2.0) / ih)
        wn = _clamp01(w / iw)
        hn = _clamp01(h / ih)
        if wn <= 0.0 or hn <= 0.0:   # dejenere kutu (sıfır alan) → at
            skipped += 1
            continue
        out[file_name].append((idx, xc, yc, wn, hn))
        class_counts[target_classes[idx]] += 1

    return out, class_counts, skipped


def write_yolo_labels(boxes_by_file: Dict[str, List[YoloBox]], labels_dir: str) -> int:
    """Dosya-bazlı YOLO kutularını <labels_dir>/<stem>.txt olarak yazar. Yazılan dosya sayısını döner."""
    os.makedirs(labels_dir, exist_ok=True)
    written = 0
    for file_name, boxes in boxes_by_file.items():
        stem = os.path.splitext(os.path.basename(file_name))[0]
        path = os.path.join(labels_dir, f"{stem}.txt")
        # Kutu yoksa bile boş etiket dosyası yaz: YOLO bunu "negatif örnek" sayar (arka plan).
        with open(path, "w", encoding="utf-8") as f:
            for (cls, xc, yc, wn, hn) in boxes:
                f.write(f"{cls} {xc:.6f} {yc:.6f} {wn:.6f} {hn:.6f}\n")
        written += 1
    return written


def convert_coco(json_path: str, out_root: str, split: str = "train") -> dict:
    """COCO JSON dosyasını okuyup birleşik kümeye (out_root/labels/<split>) etiket yazar.

    Dönüş: istatistik sözlüğü (görüntü/kutu sayısı, sınıf dağılımı, atlanan).
    """
    with open(json_path, "r", encoding="utf-8") as f:
        coco = json.load(f)
    boxes_by_file, class_counts, skipped = coco_to_yolo(coco)
    labels_dir = os.path.join(out_root, "labels", split)
    written = write_yolo_labels(boxes_by_file, labels_dir)
    stats = {
        "images": written,
        "boxes": int(sum(class_counts.values())),
        "per_class": dict(class_counts),
        "skipped": skipped,
        "labels_dir": labels_dir,
    }
    print(f"COCO→YOLO: {stats['images']} görüntü, {stats['boxes']} kutu, "
          f"{skipped} atlandı -> {labels_dir}")
    for name, n in sorted(class_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {name:14s} {n}")
    return stats


# ──────────────────────────────────────────────────────────────────────────────
# 4) Veri seti denetimi (plan.md Bölüm 4.1 sınıf dengesi + Bölüm 11 sızıntı riski)
# ──────────────────────────────────────────────────────────────────────────────
def validate_label_text(text: str, n_classes: int) -> Tuple[List[YoloBox], List[str]]:
    """Bir YOLO etiket dosyasının içeriğini doğrular (saf fonksiyon).

    Dönüş: (geçerli kutular, hata mesajları). Kontroller: 5 alan, tamsayı sınıf,
    sınıf aralığı [0, n_classes), koordinatlar (0,1] (genişlik/yükseklik > 0).
    """
    boxes: List[YoloBox] = []
    errors: List[str] = []
    for ln, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) != 5:
            errors.append(f"satır {ln}: 5 alan bekleniyor, {len(parts)} bulundu")
            continue
        try:
            cls = int(parts[0])
            xc, yc, wn, hn = (float(p) for p in parts[1:])
        except ValueError:
            errors.append(f"satır {ln}: sayıya çevrilemeyen alan")
            continue
        if cls < 0 or cls >= n_classes:
            errors.append(f"satır {ln}: sınıf {cls} aralık dışı [0,{n_classes})")
            continue
        if not (0.0 <= xc <= 1.0 and 0.0 <= yc <= 1.0 and 0.0 < wn <= 1.0 and 0.0 < hn <= 1.0):
            errors.append(f"satır {ln}: koordinat 0-1 dışında ({xc},{yc},{wn},{hn})")
            continue
        boxes.append((cls, xc, yc, wn, hn))
    return boxes, errors


def _stems_in(dir_path: str, exts: Tuple[str, ...]) -> Dict[str, str]:
    """Klasördeki dosyaların {stem: dosya_adı} eşlemesi (verilen uzantılarla)."""
    out: Dict[str, str] = {}
    if not os.path.isdir(dir_path):
        return out
    for fn in os.listdir(dir_path):
        if fn.lower().endswith(exts):
            out[os.path.splitext(fn)[0]] = fn
    return out


def audit_dataset(root: str, splits: Tuple[str, ...] = ("train", "val", "test")) -> dict:
    """Birleşik YOLO kümesini denetler ve makine-okunur bir rapor döndürür.

    Rapor: bölme başına görüntü/etiket/kutu sayısı, sınıf başına kutu (denge için),
    format hataları, train/val/test sızıntısı (aynı stem birden çok bölmede),
    yetim görüntü (etiketsiz) ve yetim etiket (görüntüsüz).
    """
    n_classes = len(TARGET_CLASSES)
    report = {
        "root": root,
        "per_split": {},
        "class_counts": Counter(),
        "errors": [],
        "leakage": [],
        "orphan_images": [],   # görüntü var, etiket yok
        "orphan_labels": [],   # etiket var, görüntü yok
        "total_boxes": 0,
    }
    stems_per_split: Dict[str, set] = {}

    for split in splits:
        img_dir = os.path.join(root, "images", split)
        lbl_dir = os.path.join(root, "labels", split)
        img_stems = _stems_in(img_dir, IMAGE_EXTS)
        lbl_stems = _stems_in(lbl_dir, (".txt",))
        stems_per_split[split] = set(img_stems) | set(lbl_stems)

        boxes_total = 0
        for stem, fn in lbl_stems.items():
            path = os.path.join(lbl_dir, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    boxes, errs = validate_label_text(f.read(), n_classes)
            except OSError as e:
                report["errors"].append(f"{split}/{fn}: okunamadı ({e})")
                continue
            for e in errs:
                report["errors"].append(f"{split}/{fn}: {e}")
            for (cls, *_rest) in boxes:
                report["class_counts"][TARGET_CLASSES[cls]] += 1
            boxes_total += len(boxes)

        # Yetim tespiti: görüntü-etiket eşleşmesi (negatif örnekler için boş .txt normaldir,
        # ama hiç .txt olmaması "etiketlenmemiş görüntü" demektir → uyarı).
        report["orphan_images"] += [f"{split}/{img_stems[s]}" for s in img_stems if s not in lbl_stems]
        report["orphan_labels"] += [f"{split}/{lbl_stems[s]}" for s in lbl_stems if s not in img_stems]

        report["per_split"][split] = {
            "images": len(img_stems),
            "labels": len(lbl_stems),
            "boxes": boxes_total,
        }
        report["total_boxes"] += boxes_total

    # Sızıntı: aynı stem birden fazla bölmede (veri sızıntısı = şişirilmiş metrik, plan B.11)
    all_splits = list(splits)
    for i in range(len(all_splits)):
        for j in range(i + 1, len(all_splits)):
            common = stems_per_split.get(all_splits[i], set()) & stems_per_split.get(all_splits[j], set())
            for stem in sorted(common):
                report["leakage"].append(f"{stem} ({all_splits[i]} ∩ {all_splits[j]})")

    return report


def print_audit(report: dict) -> None:
    """audit_dataset raporunu insan-okunur biçimde yazar."""
    print(f"=== Veri seti denetimi: {report['root']} ===")
    for split, s in report["per_split"].items():
        print(f"  {split:5s} | görüntü {s['images']:6d} | etiket {s['labels']:6d} | kutu {s['boxes']:7d}")
    print(f"  TOPLAM kutu: {report['total_boxes']}")
    print("  Sınıf dağılımı (denge kontrolü):")
    cc = report["class_counts"]
    for name in TARGET_CLASSES:  # sabit sırada → eksik sınıf 0 olarak görünür
        print(f"    {name:14s} {cc.get(name, 0)}")
    if report["leakage"]:
        print(f"  ⚠ SIZINTI ({len(report['leakage'])}): aynı kare birden çok bölmede!")
        for x in report["leakage"][:10]:
            print(f"    - {x}")
    if report["errors"]:
        print(f"  ⚠ FORMAT HATASI ({len(report['errors'])}):")
        for x in report["errors"][:10]:
            print(f"    - {x}")
    if report["orphan_images"]:
        print(f"  ⚠ Etiketsiz görüntü: {len(report['orphan_images'])}")
    if report["orphan_labels"]:
        print(f"  ⚠ Görüntüsüz etiket: {len(report['orphan_labels'])}")
    ok = not (report["leakage"] or report["errors"] or report["orphan_labels"])
    print("  Sonuç:", "TEMİZ ✓" if ok else "DÜZELTME GEREKİR ⚠")


# ──────────────────────────────────────────────────────────────────────────────
# 5) data.yaml ↔ TARGET_CLASSES tutarlılığı (plan tekrar tekrar vurguluyor)
# ──────────────────────────────────────────────────────────────────────────────
def parse_yaml_names(data_yaml_text: str) -> List[str]:
    """data.yaml içindeki 'names:' eşlemesini sıralı ada listesine çevirir.

    PyYAML bağımlılığından kaçınmak için minik, biçime-özel ayrıştırıcı: 'names:'
    satırından sonra gelen girintili '  <idx>: <ad>' satırlarını okur. Bizim
    data.yaml biçimimiz için yeterli; karmaşık YAML için ultralytics zaten yaml kullanır.
    """
    names: Dict[int, str] = {}
    in_names = False
    for line in data_yaml_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("names:"):
            in_names = True
            continue
        if in_names:
            # Girinti bitti (yeni üst-seviye anahtar) → names bloğu sona erdi.
            if not (line.startswith(" ") or line.startswith("\t")):
                break
            if ":" in stripped:
                key, val = stripped.split(":", 1)
                try:
                    idx = int(key.strip())
                except ValueError:
                    continue
                names[idx] = val.strip()
    return [names[i] for i in sorted(names)]


def check_classes(data_yaml_path: str) -> Tuple[bool, str]:
    """data.yaml sınıfları config/settings.py:TARGET_CLASSES ile birebir mi?

    Dönüş: (uyumlu_mu, açıklama_mesajı). Uyumsuzluk eğitim/çıkarım arası sessiz
    sınıf kayması demektir (yanlış etiket indeksi) — bu yüzden sabit kontrol edilir.
    """
    with open(data_yaml_path, "r", encoding="utf-8") as f:
        yaml_names = parse_yaml_names(f.read())
    if yaml_names == list(TARGET_CLASSES):
        return True, f"Tutarlı ✓ ({len(yaml_names)} sınıf): {yaml_names}"
    return False, (f"UYUMSUZ ⚠\n  data.yaml      : {yaml_names}\n"
                   f"  TARGET_CLASSES : {list(TARGET_CLASSES)}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def main():
    # Windows konsolu varsayılan kod sayfası (cp1254) ✓/⚠ gibi sembolleri yazamaz →
    # stdout'u UTF-8'e al (hedef platform Windows, bkz. PROGRESS R1). Desteklenmezse sessizce geç.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="YOL Güvenliği veri hazırlama araçları")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pf = sub.add_parser("frames", help="videodan kare çıkar")
    pf.add_argument("--video", required=True)
    pf.add_argument("--out", default="datasets/raw")
    pf.add_argument("--fps", type=float, default=2.0)

    ps = sub.add_parser("scaffold", help="YOLO klasör iskeleti")
    ps.add_argument("--root", default="datasets/yolguvenligi")

    pc = sub.add_parser("coco", help="COCO JSON → birleşik YOLO etiketleri")
    pc.add_argument("--json", required=True, help="COCO instances .json")
    pc.add_argument("--out", default="datasets/yolguvenligi", help="birleşik küme kökü")
    pc.add_argument("--split", default="train", choices=("train", "val", "test"))

    pa = sub.add_parser("audit", help="birleşik kümeyi denetle")
    pa.add_argument("--root", default="datasets/yolguvenligi")

    pv = sub.add_parser("verify", help="data.yaml ↔ TARGET_CLASSES tutarlılığı")
    pv.add_argument("--data", default="ai/training/data.yaml")

    args = ap.parse_args()
    if args.cmd == "frames":
        extract_frames(args.video, args.out, args.fps)
    elif args.cmd == "scaffold":
        scaffold(args.root)
    elif args.cmd == "coco":
        convert_coco(args.json, args.out, args.split)
    elif args.cmd == "audit":
        print_audit(audit_dataset(args.root))
    elif args.cmd == "verify":
        ok, msg = check_classes(args.data)
        print(msg)
        raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
