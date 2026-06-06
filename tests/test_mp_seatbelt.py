"""
Emniyet kemeri tespiti (ai/mp_seatbelt.py) + sürücü füzyonu testleri.

Mock-first (K4): mediapipe kurulu olsa bile mode='mock' ile zorlanır → deterministik.
Doğrulanan sözleşme:
  1) Mock modda ASLA bayrak üretilmez (boş SeatbeltSignal).
  2) DriverState.seatbelt_on default None (bilinmiyor) — kontrat güvenli.
  3) Füzyon: torso_found + no_seatbelt → state.no_seatbelt=True ve risk faktörü.
"""
import numpy as np

from ai.mp_seatbelt import SeatbeltDetector, SeatbeltSignal
from ai.driver_state import DriverMonitor
from ai.schema import DriverState, BBox
from ai.risk import assess_risk
from config.settings import get_settings


def test_seatbelt_mock_never_fabricates():
    sd = SeatbeltDetector(settings=get_settings(), mode="mock")
    frame = (np.random.rand(240, 160, 3) * 255).astype("uint8")
    sig = sd.detect(frame)
    assert isinstance(sig, SeatbeltSignal)
    assert sig.torso_found is False
    assert sig.belt_on is False and sig.no_seatbelt is False


def test_seatbelt_mock_handles_empty():
    sd = SeatbeltDetector(settings=get_settings(), mode="mock")
    assert sd.detect(None).no_seatbelt is False
    assert sd.detect(np.zeros((0, 0, 3), dtype="uint8")).torso_found is False


def test_driverstate_seatbelt_default_unknown():
    assert DriverState().seatbelt_on is None
    assert DriverState().no_seatbelt is False


def test_disabled_via_config_falls_back_to_mock():
    s = get_settings()
    s.seatbelt_enabled = False
    try:
        sd = SeatbeltDetector(settings=s, mode="auto")
        assert sd.mode == "mock"
        assert sd.detect((np.random.rand(120, 120, 3) * 255).astype("uint8")).no_seatbelt is False
    finally:
        s.seatbelt_enabled = True


def test_fusion_no_seatbelt_sets_flag_and_risk(monkeypatch):
    """torso_found + no_seatbelt → state.no_seatbelt=True → risk faktörü 'emniyet_kemeri_yok'."""
    dm = DriverMonitor(mode="mock", settings=get_settings())
    dm.mode = "real"  # kemer dalını açmak için (gerçek Pose çağrılmaz, mock'lanır)
    monkeypatch.setattr(dm, "_fatigue_real", lambda f, d: (0.30, 0.0, False))
    monkeypatch.setattr(dm, "_detect_smoking_heuristic", lambda *a, **k: False)
    monkeypatch.setattr(
        dm.seatbelt, "detect",
        lambda *a, **k: SeatbeltSignal(torso_found=True, belt_on=False, no_seatbelt=True),
    )

    frame = (np.random.rand(240, 320, 3) * 255).astype("uint8")
    st = dm.assess(frame, [], profile="critical", vehicle_bbox=BBox(x1=0, y1=0, x2=320, y2=240))
    assert st.no_seatbelt is True and st.seatbelt_on is False

    r = assess_risk(st, speed_kmh=40)
    assert "emniyet_kemeri_yok" in r.factors


def test_fusion_belt_on_no_flag(monkeypatch):
    """Kemer takılıysa no_seatbelt=False, risk faktörü oluşmaz."""
    dm = DriverMonitor(mode="mock", settings=get_settings())
    dm.mode = "real"
    monkeypatch.setattr(dm, "_fatigue_real", lambda f, d: (0.30, 0.0, False))
    monkeypatch.setattr(dm, "_detect_smoking_heuristic", lambda *a, **k: False)
    monkeypatch.setattr(
        dm.seatbelt, "detect",
        lambda *a, **k: SeatbeltSignal(torso_found=True, belt_on=True, no_seatbelt=False),
    )
    frame = (np.random.rand(240, 320, 3) * 255).astype("uint8")
    st = dm.assess(frame, [], profile="critical", vehicle_bbox=BBox(x1=0, y1=0, x2=320, y2=240))
    assert st.seatbelt_on is True and st.no_seatbelt is False
    assert "emniyet_kemeri_yok" not in assess_risk(st, speed_kmh=40).factors
