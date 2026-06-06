"""
Harici bir YOLO veri setini (kendi data.yaml'ı olan) **sınıf-adı eşlemesiyle** birleşik
kümeye katar (plan.md Bölüm 5 — heterojen kaynakları tek şemada toplama).

Neden var: Roboflow/açık setler kendi sınıf adları + indeksleriyle gelir (ör. minibüs
setinde Minibus=1, car=3). İndeks-bazlı kopyalama yanlış olur. Bu araç eşlemeyi **ada göre**
yapar (sağlam), bizim TARGET_CLASSES indeksine çevirir, eşlenmeyen sınıfları düşürür ve
imajları birleşik kümenin uygun split'ine kopyalar.

Önemli: yalnız **en az bir eşlenen kutusu olan** imajlar alınır (boş kalan imaj =
etiketlenmemiş nesne riski → atlanır). Eşlenmeyen sınıflar (ör. Ambulance) düşürülür.

Kullanım:
  python -m ai.training.merge_yolo --ext-root datasets/raw/minibus_rf \
      --out datasets/yolguvenligi \
      --map Minibus=minibus --map car=car \
      --route train=train --route test=train --route valid=val
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import Counter
from typing import Dict, List

from config.settings import TARGET_CLASSES
from ai.training.prepare_dataset import parse_yaml_names

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def remap_label_text(text: str, ext_names: List[str],
                     name_map: Dict[str, str], our_idx: Dict[str, int]) -> List[str]:
    """Harici etiket satırlarını TARGET indeksine çevirir; eşlenmeyen sınıfları düşürür.

    Dönüş: yeniden indekslenmiş YOLO satırları (eşlenen kutu yoksa boş liste).
    """
    out: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) != 5:
            continue
        try:
            ei = int(parts[0])
        except ValueError:
            continue
        if ei < 0 or ei >= len(ext_names):
            continue
        our_name = name_map.get(ext_names[ei])
        if not our_name:                      # eşlenmeyen sınıf → düşür
            continue
        out.append(f"{our_idx[our_name]} {parts[1]} {parts[2]} {parts[3]} {parts[4]}")
    return out


def read_class_names(data_yaml_path: str) -> List[str]:
    """data.yaml 'names'ini okur — hem liste (`- ad`, ultralytics/Roboflow) hem dict
    (`0: ad`, bizim biçim) formatını destekler. Sıralı ad listesi döner."""
    with open(data_yaml_path, "r", encoding="utf-8") as f:
        text = f.read()
    # Önce dict biçimini dene (bizim format)
    names = parse_yaml_names(text)
    if names:
        return names
    # Liste biçimi: 'names:' sonrası girintili '- ad' satırları
    out: List[str] = []
    in_names = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("names:"):
            in_names = True
            continue
        if in_names:
            if stripped.startswith("- "):
                out.append(stripped[2:].strip())
            elif stripped and not line[:1].isspace() and not stripped.startswith("-"):
                break          # yeni üst-seviye anahtar → names bitti
    return out


def _stem(fn: str) -> str:
    return os.path.splitext(os.path.basename(fn))[0]


def merge(ext_root: str, out_root: str, name_map: Dict[str, str],
          routing: Dict[str, str]) -> dict:
    ext_names = read_class_names(os.path.join(ext_root, "data.yaml"))
    if not ext_names:
        raise SystemExit(f"{ext_root}/data.yaml içinde 'names' bulunamadı")
    our_idx = {n: i for i, n in enumerate(TARGET_CLASSES)}
    for v in name_map.values():
        if v not in our_idx:
            raise SystemExit(f"hedef sınıf TARGET_CLASSES'ta yok: {v}")
    print(f"Harici sınıflar: {ext_names}")
    print(f"Eşleme: {name_map}  (eşlenmeyenler düşürülür)")

    stats = {"per_split": {}, "per_class": Counter(), "kept": 0, "dropped_empty": 0}
    for ext_split, our_split in routing.items():
        img_dir_in = os.path.join(ext_root, ext_split, "images")
        lbl_dir_in = os.path.join(ext_root, ext_split, "labels")
        if not os.path.isdir(img_dir_in):
            print(f"  (atlandı: {ext_split} yok)")
            continue
        img_out = os.path.join(out_root, "images", our_split)
        lbl_out = os.path.join(out_root, "labels", our_split)
        os.makedirs(img_out, exist_ok=True)
        os.makedirs(lbl_out, exist_ok=True)

        kept = dropped = 0
        for fn in os.listdir(img_dir_in):
            if not fn.lower().endswith(IMAGE_EXTS):
                continue
            stem = _stem(fn)
            lbl_path = os.path.join(lbl_dir_in, stem + ".txt")
            if not os.path.isfile(lbl_path):
                continue
            with open(lbl_path, "r", encoding="utf-8") as f:
                lines = remap_label_text(f.read(), ext_names, name_map, our_idx)
            if not lines:                     # eşlenen kutu yok → atla (etiketlenmemiş risk)
                dropped += 1
                continue
            # benzersiz ad (harici set öneki) → COCO dosyalarıyla çakışmaz
            base = f"ext_{ext_split}_{stem}"
            shutil.copy2(os.path.join(img_dir_in, fn), os.path.join(img_out, base + os.path.splitext(fn)[1]))
            with open(os.path.join(lbl_out, base + ".txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            for ln in lines:
                stats["per_class"][TARGET_CLASSES[int(ln.split()[0])]] += 1
            kept += 1
        stats["per_split"][f"{ext_split}->{our_split}"] = {"kept": kept, "dropped_empty": dropped}
        stats["kept"] += kept
        stats["dropped_empty"] += dropped
        print(f"  {ext_split} -> {our_split}: {kept} eklendi, {dropped} atlandı (boş)")

    print("Eklenen kutu dağılımı:")
    for name in TARGET_CLASSES:
        if stats["per_class"].get(name):
            print(f"  {name:14s} +{stats['per_class'][name]}")
    return stats


def _parse_kv(items: List[str], sep: str = "=") -> Dict[str, str]:
    out = {}
    for it in items or []:
        if sep not in it:
            raise SystemExit(f"geçersiz eşleme '{it}', 'A{sep}B' bekleniyor")
        k, v = it.split(sep, 1)
        out[k.strip()] = v.strip()
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Harici YOLO setini ad-eşlemeyle birleşik kümeye kat")
    ap.add_argument("--ext-root", required=True, help="harici set kökü (data.yaml içermeli)")
    ap.add_argument("--out", default="datasets/yolguvenligi", help="birleşik küme kökü")
    ap.add_argument("--map", action="append", default=[], metavar="ExtAd=BizimAd",
                    help="sınıf-adı eşlemesi (tekrarlanabilir)")
    ap.add_argument("--route", action="append", default=[], metavar="ext_split=bizim_split",
                    help="split yönlendirme (tekrarlanabilir; ör. train=train test=train valid=val)")
    args = ap.parse_args()
    name_map = _parse_kv(args.map)
    routing = _parse_kv(args.route) or {"train": "train", "test": "train", "valid": "val"}
    if not name_map:
        raise SystemExit("en az bir --map gerekir (ör. --map Minibus=minibus)")
    merge(args.ext_root, args.out, name_map, routing)


if __name__ == "__main__":
    main()
