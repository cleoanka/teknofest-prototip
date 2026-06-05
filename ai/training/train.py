"""
Model fine-tuning / transfer learning hattı (ultralytics YOLOv8) — plan.md Bölüm 6 & 9.

Neden var: Eğitilmiş özel model yok → COCO ön-eğitimli ağırlıktan başlayıp aşamalı
müfredatla fine-tune ediyoruz (plan 6.1). Bu modül üç şeyi yapar:

  1) **Aşamalı müfredat** (--curriculum): ısınma (omurga donuk, kısa tur) → ana
     fine-tune (tüm 7 sınıf, 80 epoch) → (opsiyonel) saha-uyarlama (komite/TOGG
     verisi gelince düşük lr). Her aşama bir öncekinin `best.pt`'sinden devam eder.
  2) **İki kademe** (--tier): Normal mod hafif `yolov8n` (yüksek FPS), Kritik mod
     `yolov8s` (7 sınıf doğruluğu). QoD mimarisiyle uyumlu (plan Bölüm 3).
  3) **Doğru export** (--export): ONNX / ONNX-fp16 / TensorRT-INT8. INT8 kalibrasyon
     verisi ister (eski sürümdeki "data'sız int8" hatası düzeltildi, plan Bölüm 9).

TASARIM: Orkestrasyon mantığı (hangi aşama, hangi hiperparametre, hangi export
kwargs) **saf fonksiyonlarda** tutuldu → ultralytics/GPU olmadan test edilir (K4).
Gerçek eğitim yalnız `run_stage()` içinde ultralytics'i çağırır. `--dry-run` ile
plan, tek satır eğitim koşturmadan görülebilir (4060'ta bulut öncesi doğrulama).

Kullanım:
  # Planı gör (GPU gerekmez):
  python -m ai.training.train --tier critical --curriculum --dry-run
  # Ana eğitim (kritik kademe, müfredatlı):
  python -m ai.training.train --data ai/training/data.yaml --tier critical \
      --curriculum --epochs 80 --device auto --export engine-int8
  # Komite verisi gelince saha-uyarlama ekle:
  python -m ai.training.train --data ai/training/data.yaml --field-data saha.yaml --curriculum

Çıktı: runs/detect/<name>*/weights/best.pt  ->  .env'de YOLO_MODEL_CRITICAL yap.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ──────────────────────────────────────────────────────────────────────────────
# Varsayılanlar (plan Bölüm 6.3 hiperparametre tablosu)
# ──────────────────────────────────────────────────────────────────────────────

# İki kademe: hafif (normal/yüksek FPS) vs doğruluk (kritik/7 sınıf) — plan Bölüm 3.
TIER_DEFAULTS: Dict[str, Dict[str, object]] = {
    "normal":   {"base": "yolov8n.pt", "imgsz": 640},   # nano: ~25-40 FPS (4060)
    "critical": {"base": "yolov8s.pt", "imgsz": 640},   # small: 7 sınıf doğruluğu
}

# Tam augmentation (genelleme zorunlu: farklı araç/açı/hava — şartname) — plan 6.2.
FULL_AUG: Dict[str, float] = dict(
    mosaic=1.0, mixup=0.1,
    hsv_h=0.015, hsv_s=0.7, hsv_v=0.4,   # renk jitter (gece/gündüz)
    degrees=5.0, translate=0.1, scale=0.5, fliplr=0.5,
)
# Hafif augmentation: ısınma ve saha-uyarlama turlarında (katastrofik bozulmayı azalt).
LIGHT_AUG: Dict[str, float] = dict(
    mosaic=0.5, mixup=0.0,
    hsv_h=0.015, hsv_s=0.5, hsv_v=0.3,
    degrees=3.0, translate=0.05, scale=0.3, fliplr=0.5,
)

EXPORT_MODES = ("onnx", "onnx-fp16", "engine-int8")


@dataclass
class Stage:
    """Tek bir eğitim aşamasının tam tanımı (ultralytics model.train kwargs'ına çevrilir)."""
    name: str
    base: str                       # başlangıç ağırlığı (COCO .pt veya önceki aşamanın best.pt'si)
    data: str                       # data.yaml yolu
    epochs: int
    imgsz: int
    batch: int
    device: str
    cls: float = 0.7                # nadir sınıf için sınıf-kaybı ağırlığı (focal etkisi)
    patience: int = 20              # erken durdurma
    lr0: Optional[float] = None     # None → ultralytics varsayılanı; saha turunda düşük
    freeze: Optional[int] = None    # ısınmada omurgayı dondur (ör. ilk 10 katman)
    aug: Dict[str, float] = field(default_factory=lambda: dict(FULL_AUG))
    note: str = ""

    def best_path(self) -> str:
        """Bu aşamanın üreteceği en iyi ağırlık yolu (sonraki aşama buradan devam eder)."""
        return f"runs/detect/{self.name}/weights/best.pt"

    def train_kwargs(self) -> dict:
        """ultralytics model.train(**kwargs) için sözlük (None alanlar elenir)."""
        kw = dict(
            data=self.data, epochs=self.epochs, imgsz=self.imgsz, batch=self.batch,
            device=self.device, name=self.name, cls=self.cls, patience=self.patience,
            seed=42, **self.aug,
        )
        if self.lr0 is not None:
            kw["lr0"] = self.lr0
        if self.freeze is not None:
            kw["freeze"] = self.freeze
        return kw


# ──────────────────────────────────────────────────────────────────────────────
# Saf orkestrasyon mantığı (test edilebilir — GPU/ultralytics gerekmez)
# ──────────────────────────────────────────────────────────────────────────────
def resolve_tier(tier: str, base: Optional[str], imgsz: Optional[int]) -> Dict[str, object]:
    """Kademe varsayılanlarını uygula; açıkça verilen base/imgsz önceliklidir."""
    d = TIER_DEFAULTS.get(tier)
    if d is None:
        raise ValueError(f"bilinmeyen kademe: {tier} (geçerli: {list(TIER_DEFAULTS)})")
    return {
        "base": base if base else d["base"],
        "imgsz": imgsz if imgsz else d["imgsz"],
    }


def build_curriculum(
    *, data: str, base: str, epochs: int, imgsz: int, batch: int, device: str,
    name: str, curriculum: bool, field_data: Optional[str] = None,
) -> List[Stage]:
    """Aşama listesini kurar (plan 6.1). Aşamalar `base` üzerinden zincirlenir.

    - curriculum=False → tek aşama (ana fine-tune). Geriye-dönük uyumlu.
    - curriculum=True  → ısınma (omurga donuk, kısa) + ana.
    - field_data       → en sona düşük-lr saha-uyarlama aşaması eklenir.
    """
    stages: List[Stage] = []
    main_base = base

    if curriculum:
        # 1) Isınma: omurgayı dondur, kısa tur → tespit başlığı sürüş alanına ısınır,
        #    ucuz ve katastrofik unutmayı azaltır (plan 6.1 adım 2'nin uygulanabilir biçimi).
        warm_epochs = max(5, epochs // 8)
        stages.append(Stage(
            name=f"{name}_warmup", base=base, data=data, epochs=warm_epochs,
            imgsz=imgsz, batch=batch, device=device, freeze=10,
            patience=max(5, warm_epochs // 2), aug=dict(LIGHT_AUG),
            note="omurga ısınma (freeze=10, kısa tur)",
        ))
        main_base = stages[-1].best_path()   # ana aşama ısınmanın best.pt'sinden devam

    # 2) Ana fine-tune: tüm 7 sınıf, tam augmentation, erken durdurma.
    stages.append(Stage(
        name=name, base=main_base, data=data, epochs=epochs, imgsz=imgsz,
        batch=batch, device=device, patience=20, aug=dict(FULL_AUG),
        note="ana fine-tune (tüm 7 sınıf, tam augmentation)",
    ))

    # 3) Saha-uyarlama (opsiyonel): düşük lr, hafif aug → komite verisine ince ayar.
    if field_data:
        stages.append(Stage(
            name=f"{name}_field", base=stages[-1].best_path(), data=field_data,
            epochs=max(10, epochs // 4), imgsz=imgsz, batch=batch, device=device,
            lr0=0.001, patience=10, aug=dict(LIGHT_AUG),
            note="saha-uyarlama (düşük lr=0.001, katastrofik unutmayı önle)",
        ))

    return stages


def export_kwargs(mode: str, imgsz: int, data: Optional[str]) -> dict:
    """Export modunu ultralytics model.export(**kwargs)'a çevirir (plan Bölüm 9).

    - onnx       : taşınabilir, fp32.
    - onnx-fp16  : ~yarı boyut/gecikme, ihmal edilebilir mAP kaybı (half=True).
    - engine-int8: TensorRT INT8 (~%20-35 hız). **Kalibrasyon verisi (data) zorunlu** —
      eski koddaki `format=onnx, int8=True` (kalibrasyonsuz) yanlıştı; düzeltildi.
    """
    if mode not in EXPORT_MODES:
        raise ValueError(f"geçersiz export modu: {mode} (geçerli: {EXPORT_MODES})")
    if mode == "onnx":
        return {"format": "onnx", "imgsz": imgsz}
    if mode == "onnx-fp16":
        return {"format": "onnx", "half": True, "imgsz": imgsz}
    # engine-int8
    if not data:
        raise ValueError("INT8 export kalibrasyon verisi ister: --data <data.yaml> ver.")
    return {"format": "engine", "int8": True, "data": data, "imgsz": imgsz}


def format_plan(stages: List[Stage], export: Optional[str]) -> str:
    """Müfredatı insan-okunur özetler (--dry-run çıktısı)."""
    lines = [f"Eğitim planı: {len(stages)} aşama"]
    for i, s in enumerate(stages, 1):
        extra = []
        if s.freeze is not None:
            extra.append(f"freeze={s.freeze}")
        if s.lr0 is not None:
            extra.append(f"lr0={s.lr0}")
        extra_s = (" [" + ", ".join(extra) + "]") if extra else ""
        lines.append(
            f"  {i}. {s.name}: base={s.base} | data={s.data} | "
            f"epochs={s.epochs} imgsz={s.imgsz} batch={s.batch}{extra_s}"
        )
        lines.append(f"     → {s.note}; çıktı: {s.best_path()}")
    lines.append(f"Export: {export or '(yok)'}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Gerçek koşum (yalnız burada ultralytics/GPU gerekir)
# ──────────────────────────────────────────────────────────────────────────────
def resolve_device(device: str) -> str:
    """'auto' → cuda/mps/cpu. (4060'da cuda, Mac'te mps.)"""
    if device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def run_stage(stage: Stage) -> str:
    """Tek aşamayı eğitir ve değerlendirir. best.pt yolunu döner."""
    from ultralytics import YOLO
    model = YOLO(stage.base)
    model.train(**stage.train_kwargs())
    # Tercihen 'test' bölmesinde değerlendir; bazı veri setlerinde (ör. coco8) test
    # bölmesi yok → 'val'e nazikçe düş (eğitim yine de tamamlanmış sayılır).
    try:
        metrics = model.val(data=stage.data, device=stage.device, split="test")
    except Exception:
        print(f"[{stage.name}] test bölmesi yok → val ile değerlendiriliyor")
        metrics = model.val(data=stage.data, device=stage.device, split="val")
    print(f"[{stage.name}] mAP50:", getattr(metrics.box, "map50", None),
          "mAP50-95:", getattr(metrics.box, "map", None))
    return stage.best_path()


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows konsolu (cp1254) için (R1)
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="YOL Güvenliği YOLO fine-tune (müfredatlı, iki-kademe)")
    ap.add_argument("--data", default="ai/training/data.yaml")
    ap.add_argument("--tier", default="critical", choices=tuple(TIER_DEFAULTS),
                    help="normal=yolov8n (FPS) | critical=yolov8s (7 sınıf)")
    ap.add_argument("--base", default=None, help="başlangıç ağırlığı (boşsa kademe varsayılanı)")
    ap.add_argument("--imgsz", type=int, default=None, help="boşsa kademe varsayılanı (640)")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--device", default="auto", help="auto|cpu|mps|cuda|0")
    ap.add_argument("--name", default="yolguvenligi")
    ap.add_argument("--curriculum", action="store_true",
                    help="aşamalı müfredat: ısınma → ana (plan 6.1)")
    ap.add_argument("--field-data", default=None,
                    help="komite/TOGG data.yaml → sona saha-uyarlama aşaması ekle")
    ap.add_argument("--export", default=None, choices=EXPORT_MODES,
                    help="eğitim sonrası export modu")
    ap.add_argument("--export-int8", action="store_true",
                    help="(kısayol) --export engine-int8 ile eşdeğer")
    ap.add_argument("--dry-run", action="store_true",
                    help="planı yazdır, eğitim koşturma (GPU gerekmez)")
    args = ap.parse_args()

    # Kademe varsayılanları + export kısayolu çözümü.
    tier = resolve_tier(args.tier, args.base, args.imgsz)
    export_mode = args.export or ("engine-int8" if args.export_int8 else None)

    device = "auto" if args.dry_run else resolve_device(args.device)
    stages = build_curriculum(
        data=args.data, base=str(tier["base"]), epochs=args.epochs, imgsz=int(tier["imgsz"]),
        batch=args.batch, device=device, name=args.name,
        curriculum=args.curriculum, field_data=args.field_data,
    )

    # Export kwargs'ı baştan doğrula (INT8 data zorunluluğu burada erken yakalanır).
    exp_kw = export_kwargs(export_mode, int(tier["imgsz"]), args.data) if export_mode else None

    if args.dry_run:
        print(format_plan(stages, export_mode))
        if exp_kw is not None:
            print("Export kwargs:", exp_kw)
        return

    try:
        import ultralytics  # noqa: F401
    except ImportError:
        raise SystemExit("ultralytics kurulu değil: pip install ultralytics (veya --dry-run kullan)")

    last_best = None
    for stage in stages:
        print(f"\n=== Aşama: {stage.name} (base={stage.base}) ===")
        last_best = run_stage(stage)

    if exp_kw is not None and last_best:
        from ultralytics import YOLO
        print(f"\n=== Export: {export_mode} ({last_best}) ===")
        YOLO(last_best).export(**exp_kw)
        print("Export tamam.")


if __name__ == "__main__":
    main()
