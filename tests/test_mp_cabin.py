"""
MediaPipe kabin analizi (ai/mp_cabin.py) + sürücü füzyonu testleri.

Mock-first (K4): mediapipe kurulu olsa bile mode='mock' ile zorlanır; testler
kütüphaneden bağımsız ve deterministik kalır. Burada doğrulanan sözleşme:
  1) Mock modda ASLA sahte sinyal üretilmez (boş CabinSignals).
  2) DriverState yeni alanları (hand_near_ear/mouth, driver_present, ...) default güvenli.
  3) Füzyon mantığı: hand_near_ear -> phone_use, hand_near_mouth -> smoking.
"""
import numpy as np

from ai.mp_cabin import CabinAnalyzer, CabinSignals
from ai.driver_state import DriverMonitor
from ai.schema import DriverState
from config.settings import get_settings


def test_cabin_mock_never_fabricates():
    """Mock modda el sinyali üretilmez — yanlış pozitif riski sıfır."""
    ca = CabinAnalyzer(settings=get_settings(), mode="mock")
    frame = (np.random.rand(200, 160, 3) * 255).astype("uint8")
    sig = ca.analyze(frame, mouth_xy=(80, 100), ear_xys=[(10, 50), (150, 50)], face_width=120)
    assert isinstance(sig, CabinSignals)
    assert sig.hands_detected == 0
    assert sig.hand_near_ear is False and sig.hand_near_mouth is False


def test_cabin_mock_handles_empty_roi():
    ca = CabinAnalyzer(settings=get_settings(), mode="mock")
    assert ca.analyze(None).hand_near_ear is False
    assert ca.analyze(np.zeros((0, 0, 3), dtype="uint8")).hands_detected == 0


def test_driverstate_new_fields_default_safe():
    """Yeni schema alanları kontratı kırmadan güvenli default'a sahip olmalı."""
    d = DriverState()
    assert d.driver_present is False
    assert d.hands_detected == 0
    assert d.hand_near_ear is False and d.hand_near_mouth is False
    assert d.driver_signature is None and d.driver_changed is False


def test_assess_mock_mode_runs_clean():
    """Mock DriverMonitor uçtan uca çalışır, el sinyalleri pasif kalır (K4)."""
    dm = DriverMonitor(mode="mock", settings=get_settings())
    frame = (np.random.rand(480, 640, 3) * 255).astype("uint8")
    st = dm.assess(frame, [], profile="critical", vehicle_bbox=None)
    assert isinstance(st, DriverState)
    assert st.hand_near_ear is False and st.driver_present is False


def test_fusion_hand_near_ear_sets_phone(monkeypatch):
    """Füzyon sözleşmesi: el-kulak sinyali phone_use'u, el-ağız smoking'i tetikler."""
    from ai.schema import BBox
    dm = DriverMonitor(mode="mock", settings=get_settings())
    dm.mode = "real"  # füzyon dalını açmak için (gerçek model çağırılmaz, mock'lanır)

    # Yüz mesh sonucu mock'la: ağız/kulak referansları + boş öznitelik
    dm._face_refs = None

    def fake_fatigue(frame, droi):
        dm._face_refs = {
            "crop": frame,
            "mouth_xy": (80.0, 100.0),
            "ear_xys": [(10.0, 50.0), (150.0, 50.0)],
            "face_width": 120.0,
            "feats": [1.0, 0.5, 0.9, 0.3, 0.7, 0.7],
        }
        return 0.30, 0.0, False

    monkeypatch.setattr(dm, "_fatigue_real", fake_fatigue)
    monkeypatch.setattr(dm, "_detect_smoking_heuristic", lambda *a, **k: False)
    monkeypatch.setattr(
        dm.cabin, "analyze",
        lambda *a, **k: CabinSignals(hands_detected=1, hand_near_ear=True, hand_near_mouth=True),
    )

    frame = (np.random.rand(240, 320, 3) * 255).astype("uint8")
    st = dm.assess(frame, [], profile="critical", vehicle_bbox=BBox(x1=0, y1=0, x2=320, y2=240))
    assert st.phone_use is True       # hand_near_ear füzyonu
    assert st.smoking is True         # hand_near_mouth füzyonu
    assert st.driver_present is True
    assert st.driver_signature is not None
