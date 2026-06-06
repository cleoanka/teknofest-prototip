"""
Harici YOLO seti birleştirme testleri (ai/training/merge_yolo.py).

Saf-mantık (ağsız, GPU'suz): ad-bazlı sınıf eşlemesi + format-bağımsız 'names' okuma (K4).
Roboflow/açık setler kendi sınıf adı+indeksiyle gelir; remap yanlış indeksi önler.
"""
from ai.training.merge_yolo import remap_label_text, read_class_names


def _our_idx():
    from config.settings import TARGET_CLASSES
    return {n: i for i, n in enumerate(TARGET_CLASSES)}


def test_remap_by_name_and_reindex():
    # Harici sıra: 0=Ambulance 1=Minibus 2=Police 3=car. Eşleme ada göre → bizim indekse.
    ext_names = ["Ambulance", "Minibus", "Police", "car"]
    name_map = {"Minibus": "minibus", "car": "car"}
    our = _our_idx()
    text = (
        "1 0.5 0.5 0.2 0.2\n"   # Minibus → minibus
        "3 0.1 0.1 0.1 0.1\n"   # car → car
        "0 0.9 0.9 0.1 0.1\n"   # Ambulance → eşlenmez, düşer
        "2 0.4 0.4 0.1 0.1\n"   # Police → düşer
    )
    out = remap_label_text(text, ext_names, name_map, our)
    assert len(out) == 2
    # satır başları bizim indeks: minibus ve car
    cls_ids = sorted(int(l.split()[0]) for l in out)
    assert cls_ids == sorted([our["minibus"], our["car"]])
    # koordinatlar korunmuş
    assert out[0].split()[1:] == ["0.5", "0.5", "0.2", "0.2"]


def test_remap_drops_all_when_no_match():
    ext_names = ["Ambulance", "Police"]
    out = remap_label_text("0 0.5 0.5 0.2 0.2\n1 0.1 0.1 0.1 0.1\n",
                           ext_names, {"Minibus": "minibus"}, _our_idx())
    assert out == []


def test_read_class_names_list_format(tmp_path):
    # ultralytics/Roboflow liste biçimi
    y = tmp_path / "data.yaml"
    y.write_text("names:\n- Ambulance\n- Minibus\n- Police\n- car\nnc: 4\ntrain: x\n", encoding="utf-8")
    assert read_class_names(str(y)) == ["Ambulance", "Minibus", "Police", "car"]


def test_read_class_names_dict_format(tmp_path):
    # bizim dict biçimi
    y = tmp_path / "data.yaml"
    y.write_text("names:\n  0: car\n  1: minibus\ntrain: x\n", encoding="utf-8")
    assert read_class_names(str(y)) == ["car", "minibus"]
