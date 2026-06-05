"""
Veri hazırlama araçları testleri (ai/training/prepare_dataset.py).

Plan.md Bölüm 5 (dönüştürme), 4.1 (sınıf dengesi), 11 (sızıntı riski) ve sürekli
vurgulanan "data.yaml ↔ TARGET_CLASSES tutarlılığı" için saf-mantık testleri.
Hepsi çevrimdışı: gerçek görüntü, indirme veya GPU gerektirmez (K4).
"""
import json

from ai.training.prepare_dataset import (
    coco_to_yolo,
    validate_label_text,
    write_yolo_labels,
    audit_dataset,
    parse_yaml_names,
    check_classes,
)
from config.settings import TARGET_CLASSES


# ── COCO → YOLO dönüştürme ──────────────────────────────────────────────────
def _mini_coco():
    """200x100 px görüntü; bir 'car' (→vehicle) ve bir 'cell phone' (→phone) kutusu."""
    return {
        "images": [{"id": 1, "file_name": "frame_001.jpg", "width": 200, "height": 100}],
        "categories": [
            {"id": 10, "name": "car"},
            {"id": 11, "name": "cell phone"},
            {"id": 12, "name": "boat"},  # haritada yok → atlanmalı
        ],
        "annotations": [
            {"image_id": 1, "category_id": 10, "bbox": [50, 20, 100, 40]},   # merkez (100,40)
            {"image_id": 1, "category_id": 11, "bbox": [0, 0, 20, 10]},
            {"image_id": 1, "category_id": 12, "bbox": [10, 10, 30, 30]},     # boat → atlanır
        ],
    }


def test_coco_to_yolo_mapping_and_normalization():
    boxes_by_file, counts, skipped = coco_to_yolo(_mini_coco())
    boxes = boxes_by_file["frame_001.jpg"]
    # boat atlandı → 2 kutu kaldı, 1 atlandı
    assert len(boxes) == 2
    assert skipped == 1
    # car → vehicle (idx 0), merkez normalize: xc=100/200=0.5, yc=40/100=0.4, w=0.5, h=0.4
    veh = [b for b in boxes if b[0] == TARGET_CLASSES.index("vehicle")][0]
    assert veh[1] == 0.5 and veh[2] == 0.4 and veh[3] == 0.5 and veh[4] == 0.4
    # cell phone → phone
    assert any(b[0] == TARGET_CLASSES.index("phone") for b in boxes)
    assert counts["vehicle"] == 1 and counts["phone"] == 1
    assert "boat" not in counts


def test_coco_to_yolo_clamps_overflowing_box():
    """Kenardan taşan kutu [0,1]'e kırpılmalı (geçersiz YOLO koordinatı üretilmez)."""
    coco = {
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 100}],
        "categories": [{"id": 1, "name": "car"}],
        "annotations": [{"image_id": 1, "category_id": 1, "bbox": [90, 90, 50, 50]}],
    }
    boxes, _, _ = coco_to_yolo(coco)
    for (_, xc, yc, wn, hn) in boxes["a.jpg"]:
        assert 0.0 <= xc <= 1.0 and 0.0 <= yc <= 1.0
        assert 0.0 < wn <= 1.0 and 0.0 < hn <= 1.0


# ── Etiket format doğrulama ─────────────────────────────────────────────────
def test_validate_label_text_accepts_valid():
    boxes, errors = validate_label_text("0 0.5 0.5 0.2 0.3\n2 0.1 0.1 0.05 0.05\n", len(TARGET_CLASSES))
    assert len(boxes) == 2 and errors == []


def test_validate_label_text_flags_errors():
    text = (
        "0 0.5 0.5 0.2\n"          # 4 alan → hata
        "99 0.5 0.5 0.2 0.3\n"     # sınıf aralık dışı → hata
        "0 1.5 0.5 0.2 0.3\n"      # koordinat 1 üstü → hata
        "0 0.5 0.5 0.0 0.3\n"      # sıfır genişlik → hata
    )
    boxes, errors = validate_label_text(text, len(TARGET_CLASSES))
    assert boxes == []
    assert len(errors) == 4


# ── Denetim: sınıf sayımı, sızıntı, yetim ───────────────────────────────────
def test_audit_counts_and_detects_leakage(tmp_path):
    root = tmp_path / "ds"
    for split in ("train", "val"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
    # train: aynı stem hem train hem val'de → SIZINTI
    (root / "images" / "train" / "img1.jpg").write_bytes(b"x")
    (root / "labels" / "train" / "img1.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (root / "images" / "val" / "img1.jpg").write_bytes(b"x")
    (root / "labels" / "val" / "img1.txt").write_text("2 0.5 0.5 0.2 0.2\n", encoding="utf-8")

    rep = audit_dataset(str(root), splits=("train", "val", "test"))
    assert rep["per_split"]["train"]["boxes"] == 1
    assert rep["class_counts"]["vehicle"] == 1
    assert rep["class_counts"]["person"] == 1
    assert rep["total_boxes"] == 2
    # img1 her iki bölmede → sızıntı raporlanmalı
    assert any("img1" in x for x in rep["leakage"])


def test_audit_flags_orphan_label(tmp_path):
    root = tmp_path / "ds"
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    # Görüntüsü olmayan etiket → yetim etiket
    (root / "labels" / "train" / "ghost.txt").write_text("0 0.5 0.5 0.1 0.1\n", encoding="utf-8")
    rep = audit_dataset(str(root), splits=("train",))
    assert any("ghost" in x for x in rep["orphan_labels"])


def test_write_yolo_labels_roundtrip(tmp_path):
    boxes_by_file = {"x.jpg": [(0, 0.5, 0.5, 0.2, 0.2)], "empty.jpg": []}
    n = write_yolo_labels(boxes_by_file, str(tmp_path))
    assert n == 2
    # Boş örnek için bile dosya yazılır (negatif/arka plan örneği)
    assert (tmp_path / "empty.txt").exists()
    assert (tmp_path / "x.txt").read_text(encoding="utf-8").strip() == "0 0.500000 0.500000 0.200000 0.200000"


# ── data.yaml ↔ TARGET_CLASSES tutarlılığı (gerçek repo dosyası) ─────────────
def test_parse_yaml_names_basic():
    text = "path: x\nnames:\n  0: vehicle\n  1: license_plate\ntrain: y\n"
    assert parse_yaml_names(text) == ["vehicle", "license_plate"]


def test_data_yaml_matches_target_classes():
    """Repo'daki gerçek data.yaml, kanonik sınıf listesiyle birebir aynı olmalı."""
    ok, msg = check_classes("ai/training/data.yaml")
    assert ok, msg
