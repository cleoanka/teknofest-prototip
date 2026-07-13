"""
Veri indirme manifest/planlama testleri (ai/training/fetch_data.py).

Plan.md Bölüm 4 (veri kaynakları) + Risk 11 (lisans). Saf, ağsız testler — gerçek
indirme (fetch_roboflow/fetch_http_zip) test edilmez, yalnız manifest mantığı (K4).
"""


from ai.training.fetch_data import (
    Source,
    load_sources,
    validate_sources,
    license_status,
    coverage,
    missing_classes,
    find_source,
)
from config.settings import TARGET_CLASSES


def _src(name, classes, lic="MIT", typ="roboflow", loc="w/p/1"):
    return Source(name=name, type=typ, classes=classes, location=loc, license=lic)


# ── Lisans durumu (Risk 11) ─────────────────────────────────────────────────
def test_license_status_whitelist():
    assert license_status("CC-BY-4.0") == "ok"
    assert license_status("BSD-3-Clause") == "ok"
    assert license_status("academic") == "verify"
    assert license_status("") == "verify"


# ── Doğrulama ───────────────────────────────────────────────────────────────
def test_validate_clean():
    sources = [_src("a", ["car"]), _src("b", ["phone"])]
    assert validate_sources(sources) == []


def test_validate_flags_unknown_class():
    errors = validate_sources([_src("a", ["uçak"])])
    assert any("uçak" in e for e in errors)


def test_validate_flags_duplicate_and_bad_type():
    sources = [_src("a", ["car"]), _src("a", ["phone"], typ="ftp")]
    errors = validate_sources(sources)
    assert any("tekrarlanan" in e for e in errors)
    assert any("bilinmeyen tür" in e for e in errors)


def test_validate_flags_empty_license_and_location():
    s = Source(name="x", type="roboflow", classes=["car"], location="", license="")
    errors = validate_sources([s])
    assert any("lisans" in e for e in errors)
    assert any("konum" in e for e in errors)


def test_validate_manifest_classes_mismatch():
    errors = validate_sources([_src("a", ["car"])], manifest_classes=["car"])
    assert any("uyumsuz" in e for e in errors)


# ── Kapsama / boşluk ────────────────────────────────────────────────────────
def test_coverage_maps_classes_to_sources():
    sources = [_src("a", ["car", "person"]), _src("b", ["car"])]
    cov = coverage(sources)
    assert set(cov["car"]) == {"a", "b"}
    assert cov["person"] == ["a"]


def test_missing_classes_detected():
    sources = [_src("a", ["car"])]
    miss = missing_classes(sources)
    assert "car" not in miss
    assert "headphone" in miss          # kaynağı yok → boşluk


def test_find_source():
    sources = [_src("a", ["car"])]
    assert find_source(sources, "a").name == "a"
    assert find_source(sources, "yok") is None


# ── Gerçek repo manifesti ───────────────────────────────────────────────────
def test_repo_manifest_loads_and_is_valid():
    manifest_classes, sources = load_sources()   # repo varsayılanı
    assert manifest_classes == list(TARGET_CLASSES)
    errors = validate_sources(sources, manifest_classes=manifest_classes)
    assert errors == [], errors


def test_repo_manifest_covers_every_target_class():
    """Her hedef sınıfın en az bir kaynağı olmalı (boşluk = eğitim öncesi iş)."""
    _, sources = load_sources()
    assert missing_classes(sources) == []
