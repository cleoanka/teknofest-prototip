"""
Açık kaynak veri indirme yardımcıları (plan.md Bölüm 4 — "Nereden Veri?").

Neden var: Etiketimiz yok; strateji büyük açık kaynak setlerinden (COCO/BDD/CCPD/
Roboflow) sınıf bazında havuz kurmak. Bu modül o havuzu **bildirimsel bir manifest**
(`sources.json`) üzerinden yönetir:

  - list      — kaynakları + lisans durumunu listele (ağsız).
  - coverage  — her hedef sınıfı hangi kaynak(lar) besliyor; **eksik sınıf** uyarısı (ağsız).
  - validate  — manifesti doğrula: sınıflar ⊆ TARGET_CLASSES, alanlar tam, lisans var (ağsız).
  - fetch     — gerçek indirme (Roboflow API / HTTP zip). Ağ + (Roboflow için) API anahtarı ister.

TASARIM (K4): Tüm planlama/doğrulama mantığı **saf, stdlib** (ağ gerekmez) → test edilir.
Gerçek indirme `fetch_*` fonksiyonlarında izole; kütüphane/anahtar yoksa nazik hata verir.
İndirilen veri sonra `prepare_dataset.coco`/`audit` ile birleşik kümeye dönüştürülür.

Kullanım:
  python -m ai.training.fetch_data list
  python -m ai.training.fetch_data coverage
  python -m ai.training.fetch_data validate
  python -m ai.training.fetch_data fetch --name roboflow-tr-plate --out datasets/raw
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config.settings import TARGET_CLASSES

# Yarışmada kullanımı net olan lisanslar (whitelist). Diğerleri "doğrula" işaretlenir —
# akademik/roboflow/bilinmeyen setler kullanım öncesi elle teyit edilmeli (plan Risk 11).
ALLOWED_LICENSES = {
    "CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "public-domain",
    "BSD-3-Clause", "MIT", "Apache-2.0", "own",
}
# Desteklenen kaynak türleri.
SOURCE_TYPES = {"coco_json", "http_zip", "roboflow", "manual"}


@dataclass
class Source:
    name: str
    type: str
    classes: List[str]
    location: str
    license: str
    notes: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Manifest okuma + doğrulama (saf, ağsız)
# ──────────────────────────────────────────────────────────────────────────────
def default_manifest_path() -> str:
    """Repo içindeki varsayılan sources.json yolu (çağrı dizininden bağımsız)."""
    return os.path.join(os.path.dirname(__file__), "sources.json")


def load_sources(path: Optional[str] = None) -> Tuple[List[str], List[Source]]:
    """Manifesti okur. Dönüş: (manifest hedef sınıfları, Source listesi)."""
    path = path or default_manifest_path()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sources = [
        Source(
            name=s["name"], type=s["type"], classes=list(s["classes"]),
            location=s["location"], license=s.get("license", ""), notes=s.get("notes", ""),
        )
        for s in data.get("sources", [])
    ]
    return list(data.get("target_classes", [])), sources


def license_status(lic: str) -> str:
    """'ok' (whitelist) veya 'verify' (elle teyit gerekli)."""
    return "ok" if lic in ALLOWED_LICENSES else "verify"


def validate_sources(
    sources: List[Source],
    target_classes: Optional[List[str]] = None,
    manifest_classes: Optional[List[str]] = None,
) -> List[str]:
    """Manifesti doğrular. Dönüş: hata mesajları (boşsa geçerli).

    Kontroller: benzersiz ad, geçerli tür, sınıflar ⊆ TARGET_CLASSES, lisans dolu,
    (varsa) manifest target_classes == config TARGET_CLASSES.
    """
    target = target_classes if target_classes is not None else list(TARGET_CLASSES)
    target_set = set(target)
    errors: List[str] = []

    if manifest_classes is not None and manifest_classes != target:
        errors.append(f"manifest target_classes, config TARGET_CLASSES ile uyumsuz: "
                      f"{manifest_classes} != {target}")

    seen = set()
    for s in sources:
        if s.name in seen:
            errors.append(f"{s.name}: tekrarlanan kaynak adı")
        seen.add(s.name)
        if s.type not in SOURCE_TYPES:
            errors.append(f"{s.name}: bilinmeyen tür '{s.type}' (geçerli: {sorted(SOURCE_TYPES)})")
        if not s.classes:
            errors.append(f"{s.name}: sınıf listesi boş")
        for c in s.classes:
            if c not in target_set:
                errors.append(f"{s.name}: '{c}' TARGET_CLASSES dışında")
        if not s.license:
            errors.append(f"{s.name}: lisans belirtilmemiş")
        if not s.location:
            errors.append(f"{s.name}: konum (location) boş")
    return errors


def coverage(sources: List[Source], target_classes: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """Her hedef sınıfı hangi kaynaklar besliyor? Dönüş: {sınıf: [kaynak adları]}.

    Hiç kaynağı olmayan sınıflar boş liste ile döner (eğitim öncesi kapatılması gereken boşluk).
    """
    target = target_classes if target_classes is not None else list(TARGET_CLASSES)
    cov: Dict[str, List[str]] = {c: [] for c in target}
    for s in sources:
        for c in s.classes:
            if c in cov:
                cov[c].append(s.name)
    return cov


def missing_classes(sources: List[Source], target_classes: Optional[List[str]] = None) -> List[str]:
    """Hiç kaynağı olmayan hedef sınıflar (kapsama boşluğu)."""
    return [c for c, srcs in coverage(sources, target_classes).items() if not srcs]


def find_source(sources: List[Source], name: str) -> Optional[Source]:
    return next((s for s in sources if s.name == name), None)


# ──────────────────────────────────────────────────────────────────────────────
# Gerçek indirme (yalnız burada ağ / harici kütüphane gerekir)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_roboflow(source: Source, out: str, api_key: Optional[str] = None) -> str:
    """Roboflow projesini YOLO formatında indirir. `roboflow` paketi + API anahtarı ister."""
    api_key = api_key or os.environ.get("ROBOFLOW_API_KEY")
    if not api_key:
        raise SystemExit("ROBOFLOW_API_KEY yok (ortam değişkeni veya --api-key ver).")
    try:
        from roboflow import Roboflow
    except ImportError:
        raise SystemExit("roboflow kurulu değil: pip install roboflow")
    # location biçimi: "workspace/project/version"
    parts = source.location.split("/")
    if len(parts) != 3:
        raise SystemExit(f"{source.name}: roboflow location 'workspace/project/version' olmalı")
    ws, proj, ver = parts
    os.makedirs(out, exist_ok=True)
    rf = Roboflow(api_key=api_key)
    dataset = rf.workspace(ws).project(proj).version(int(ver)).download("yolov8", location=out)
    print(f"[roboflow] {source.name} -> {out}")
    return getattr(dataset, "location", out)


def fetch_http_zip(source: Source, out: str) -> str:
    """HTTP üzerinden zip indirir ve açar. (BDD/CCPD gibi setler için.)"""
    import urllib.request
    import zipfile
    if not source.location.lower().startswith(("http://", "https://")):
        raise SystemExit(f"{source.name}: http_zip için location bir URL olmalı (şu an: {source.location}). "
                         "Bu set için sayfayı ziyaret edip elle indirmen gerekebilir.")
    os.makedirs(out, exist_ok=True)
    zip_path = os.path.join(out, f"{source.name}.zip")
    print(f"[http] indiriliyor: {source.location}")
    urllib.request.urlretrieve(source.location, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out)
    print(f"[http] açıldı -> {out}")
    return out


def fetch(source: Source, out: str, api_key: Optional[str] = None) -> str:
    """Kaynağı türüne göre indirir. coco_json/manual indirme gerektirmez (yerel/elle)."""
    if source.type == "roboflow":
        return fetch_roboflow(source, out, api_key)
    if source.type == "http_zip":
        return fetch_http_zip(source, out)
    if source.type == "coco_json":
        raise SystemExit(f"{source.name}: COCO json zaten yerelde beklenir ({source.location}); "
                         "indirip prepare_dataset.coco ile dönüştür.")
    if source.type == "manual":
        raise SystemExit(f"{source.name}: elle etiketlenecek kaynak ({source.location}); otomatik indirme yok.")
    raise SystemExit(f"{source.name}: indirilemeyen tür {source.type}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────
def _print_list(sources: List[Source]) -> None:
    print(f"{'KAYNAK':28s} {'TÜR':10s} {'LİSANS':14s} {'DURUM':7s} SINIFLAR")
    for s in sources:
        st = license_status(s.license)
        flag = "✓" if st == "ok" else "⚠"
        print(f"{s.name:28s} {s.type:10s} {s.license:14s} {flag} {st:5s} {', '.join(s.classes)}")


def _print_coverage(sources: List[Source]) -> None:
    cov = coverage(sources)
    print("Sınıf kapsama (hangi kaynaklar besliyor):")
    for c in TARGET_CLASSES:
        srcs = cov.get(c, [])
        mark = "⚠ BOŞLUK" if not srcs else ""
        print(f"  {c:14s} {len(srcs)} kaynak {mark}  {', '.join(srcs)}")
    miss = missing_classes(sources)
    if miss:
        print(f"\n⚠ Kaynaksız sınıf(lar): {', '.join(miss)} — eğitimden önce kapat (etiketle/ekle).")
    else:
        print("\nTüm hedef sınıfların en az bir kaynağı var ✓")


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows konsolu (cp1254) için (R1)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Açık kaynak veri indirme yardımcıları")
    ap.add_argument("--manifest", default=None, help="sources.json yolu (boşsa repo varsayılanı)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="kaynakları + lisans durumunu listele")
    sub.add_parser("coverage", help="sınıf kapsama + eksik sınıf uyarısı")
    sub.add_parser("validate", help="manifesti doğrula")
    pf = sub.add_parser("fetch", help="bir kaynağı indir (ağ/anahtar gerekir)")
    pf.add_argument("--name", required=True)
    pf.add_argument("--out", default="datasets/raw")
    pf.add_argument("--api-key", default=None, help="Roboflow API anahtarı (yoksa ROBOFLOW_API_KEY)")

    args = ap.parse_args()
    manifest_classes, sources = load_sources(args.manifest)

    if args.cmd == "list":
        _print_list(sources)
    elif args.cmd == "coverage":
        _print_coverage(sources)
    elif args.cmd == "validate":
        errors = validate_sources(sources, manifest_classes=manifest_classes)
        if errors:
            print(f"⚠ {len(errors)} hata:")
            for e in errors:
                print(f"  - {e}")
            raise SystemExit(1)
        print(f"Manifest geçerli ✓ ({len(sources)} kaynak)")
    elif args.cmd == "fetch":
        src = find_source(sources, args.name)
        if src is None:
            raise SystemExit(f"kaynak bulunamadı: {args.name} (list ile bak)")
        fetch(src, args.out, args.api_key)


if __name__ == "__main__":
    main()
