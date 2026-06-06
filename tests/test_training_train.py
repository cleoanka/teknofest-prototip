"""
Eğitim orkestrasyonu testleri (ai/training/train.py).

Plan.md Bölüm 6.1 (aşamalı müfredat), Bölüm 3 (iki kademe n→s) ve Bölüm 9 (export).
Saf fonksiyonları test eder — ultralytics/GPU gerekmez (K4). Gerçek eğitim çağrıları
(run_stage) test edilmez; yalnız plan/kwargs mantığı doğrulanır.
"""
import pytest

from ai.training.train import (
    resolve_tier,
    build_curriculum,
    export_kwargs,
    format_plan,
    Stage,
    FULL_AUG,
    LIGHT_AUG,
)


# ── İki kademe (n→s) ────────────────────────────────────────────────────────
def test_resolve_tier_defaults():
    assert resolve_tier("normal", None, None)["base"] == "yolov8n.pt"
    assert resolve_tier("critical", None, None)["base"] == "yolov8s.pt"
    assert resolve_tier("critical", None, None)["imgsz"] == 640


def test_resolve_tier_explicit_overrides():
    r = resolve_tier("normal", "yolov8m.pt", 960)
    assert r["base"] == "yolov8m.pt" and r["imgsz"] == 960


def test_resolve_tier_unknown_raises():
    with pytest.raises(ValueError):
        resolve_tier("uydurma", None, None)


# ── Müfredat kurulumu (plan 6.1) ────────────────────────────────────────────
def _common():
    return dict(data="d.yaml", base="yolov8s.pt", epochs=80, imgsz=640,
                batch=16, device="cpu", name="yg")


def test_curriculum_off_single_stage():
    stages = build_curriculum(curriculum=False, **_common())
    assert len(stages) == 1
    assert stages[0].name == "yg"
    assert stages[0].base == "yolov8s.pt"
    assert stages[0].epochs == 80
    assert stages[0].aug == FULL_AUG


def test_curriculum_on_adds_warmup_and_chains():
    stages = build_curriculum(curriculum=True, **_common())
    assert len(stages) == 2
    warm, main = stages
    # Isınma: omurga donuk, kısa tur, hafif augmentation
    assert warm.name == "yg_warmup"
    assert warm.freeze == 10
    assert warm.epochs < main.epochs
    assert warm.aug == LIGHT_AUG
    # Ana aşama ısınmanın best.pt'sinden devam eder (zincirleme)
    assert main.base == warm.best_path()
    assert main.base == "runs/detect/yg_warmup/weights/best.pt"
    assert main.aug == FULL_AUG


def test_gentle_main_stage_uses_soft_recipe():
    # Bulgu K-008: nazik reçete → hafif aug + düşük lr0 + cos_lr (öneğitimli özellikleri korur)
    stages = build_curriculum(curriculum=True, gentle=True, **_common())
    warm, main = stages
    assert warm.aug == LIGHT_AUG          # ısınma her durumda hafif
    assert main.aug == LIGHT_AUG          # nazik ana aşama da hafif (FULL_AUG değil)
    assert main.lr0 == 0.002
    assert main.cos_lr is True
    kw = main.train_kwargs()
    assert kw["lr0"] == 0.002 and kw["cos_lr"] is True


def test_gentle_off_keeps_full_aug():
    # gentle=False (varsayılan) → ana aşama tam augmentation, lr0 None (varsayılan)
    stages = build_curriculum(curriculum=True, gentle=False, **_common())
    main = stages[-1]
    assert main.aug == FULL_AUG
    assert main.lr0 is None and main.cos_lr is False
    assert "cos_lr" not in main.train_kwargs()


def test_main_freeze_applies_to_main_stage():
    # K-008 derinleşmesi: omurga ana aşamada da donuk → genelleme korunur (küçük veri)
    stages = build_curriculum(curriculum=False, gentle=True, main_freeze=10, **_common())
    main = stages[0]
    assert main.freeze == 10
    assert main.train_kwargs()["freeze"] == 10
    # main_freeze None ise ana aşama dondurmaz
    stages2 = build_curriculum(curriculum=False, gentle=True, **_common())
    assert stages2[0].freeze is None


def test_field_adaptation_stage_appended():
    stages = build_curriculum(curriculum=True, field_data="saha.yaml", **_common())
    assert len(stages) == 3
    field = stages[-1]
    assert field.name == "yg_field"
    assert field.data == "saha.yaml"
    assert field.lr0 == 0.001                       # düşük lr (katastrofik unutma)
    assert field.base == stages[-2].best_path()     # ana aşamadan devam
    assert field.epochs < stages[-2].epochs


def test_field_without_curriculum_chains_to_main():
    stages = build_curriculum(curriculum=False, field_data="saha.yaml", **_common())
    assert len(stages) == 2
    assert stages[0].name == "yg"
    assert stages[1].base == "runs/detect/yg/weights/best.pt"


# ── Stage → train kwargs ────────────────────────────────────────────────────
def test_stage_train_kwargs_omits_none():
    s = Stage(name="x", base="b.pt", data="d.yaml", epochs=10, imgsz=640, batch=8, device="cpu")
    kw = s.train_kwargs()
    assert "lr0" not in kw and "freeze" not in kw      # None alanlar elenmeli
    assert kw["mosaic"] == 1.0 and kw["seed"] == 42
    assert kw["cls"] == 0.7


def test_stage_train_kwargs_includes_set_fields():
    s = Stage(name="x", base="b.pt", data="d.yaml", epochs=10, imgsz=640, batch=8,
              device="cpu", lr0=0.001, freeze=10)
    kw = s.train_kwargs()
    assert kw["lr0"] == 0.001 and kw["freeze"] == 10


# ── Export (plan Bölüm 9) ───────────────────────────────────────────────────
def test_export_onnx():
    assert export_kwargs("onnx", 640, None) == {"format": "onnx", "imgsz": 640}


def test_export_onnx_fp16():
    kw = export_kwargs("onnx-fp16", 640, None)
    assert kw["format"] == "onnx" and kw["half"] is True


def test_export_int8_requires_calibration_data():
    # INT8 kalibrasyon verisi olmadan hata vermeli (eski hatanın düzeltmesi)
    with pytest.raises(ValueError):
        export_kwargs("engine-int8", 640, None)


def test_export_int8_with_data():
    kw = export_kwargs("engine-int8", 640, "d.yaml")
    assert kw["format"] == "engine" and kw["int8"] is True and kw["data"] == "d.yaml"


def test_export_invalid_mode_raises():
    with pytest.raises(ValueError):
        export_kwargs("trt-fp4", 640, "d.yaml")


# ── Plan özeti (--dry-run) ──────────────────────────────────────────────────
def test_format_plan_lists_stages():
    stages = build_curriculum(curriculum=True, field_data="saha.yaml", **_common())
    text = format_plan(stages, "engine-int8")
    assert "3 aşama" in text
    assert "yg_warmup" in text and "yg_field" in text
    assert "engine-int8" in text
