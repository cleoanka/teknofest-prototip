"""
Kişi-bazlı sürücü/yolcu seçimi testleri (ai/driver_state.py select_rois + assess).

Şartname/istek: Araç yarıya bölünmez; kabindeki 'person' tespitleri arasından
KAMERANIN BAKIŞ AÇISINA göre EN SAĞ-ALTTAKİ kişi SÜRÜCÜdür. Yalnızca sürücünün
hareketleri (telefon/sigara/kulaklık) risk skoruna etki eder; yolcuların
hareketleri risk DIŞIDIR (yalnız passenger_phone olarak kayda geçer).
"""
from ai.schema import Detection, BBox
from ai.driver_state import DriverMonitor
from ai.risk import assess_risk


VEH = BBox(x1=0, y1=0, x2=1000, y2=400)
FRAME = (500, 1200)  # (H, W)


def _person(x1, y1, x2, y2):
    return Detection(label="person", confidence=0.9, bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2))


def _obj(label, x1, y1, x2, y2):
    return Detection(label=label, confidence=0.8, bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2))


def test_bottom_right_person_is_driver():
    """İki kişiden sağ-alttaki sürücü, diğeri yolcu seçilmeli."""
    dm = DriverMonitor(mode="mock")
    passenger = _person(100, 20, 300, 250)    # sol-üst
    driver = _person(600, 120, 850, 380)      # sağ-alt
    droi, pax, is_person = dm.select_rois([passenger, driver], VEH, FRAME)
    assert is_person is True
    assert (droi.x1, droi.y1, droi.x2, droi.y2) == (600, 120, 850, 380)
    assert len(pax) == 1
    assert (pax[0].x1, pax[0].y1) == (100, 20)


def test_lowest_rightmost_wins_over_merely_right():
    """Daha sağda ama yukarıda olan kişi yerine, sağ+alt bileşkesi yüksek kişi sürücü."""
    dm = DriverMonitor(mode="mock")
    high_right = _person(900, 0, 980, 60)     # çok sağda ama en üstte
    low_mid = _person(500, 300, 700, 395)     # ortada ama en altta
    droi, pax, _ = dm.select_rois([high_right, low_mid], VEH, FRAME)
    # Eşit ağırlıkta x2/W + y2/H: high_right=980/1200+60/500=0.937; low_mid=700/1200+395/500=1.373
    assert (droi.x1, droi.y1) == (500, 300)


def test_passenger_phone_excluded_from_risk():
    """Yolcunun telefonu phone_use'u YAKMAZ; passenger_phone'a yazılır; risk 0."""
    dm = DriverMonitor(mode="mock")
    passenger = _person(100, 20, 300, 250)
    driver = _person(600, 120, 850, 380)
    phone_pax = _obj("phone", 150, 80, 210, 140)   # yolcu kutusunda
    dets = [passenger, driver, phone_pax]
    droi, pax, ip = dm.select_rois(dets, VEH, FRAME)
    st = dm.assess(None, dets, "normal", vehicle_bbox=VEH,
                   driver_bbox=droi, passenger_boxes=pax, driver_is_person=ip)
    assert st.phone_use is False
    assert st.passenger_phone is True
    assert assess_risk(st, speed_kmh=40, vtype="car").score == 0


def test_driver_phone_counts_toward_risk():
    """Sürücünün telefonu phone_use'u yakar ve risk skoruna girer."""
    dm = DriverMonitor(mode="mock")
    passenger = _person(100, 20, 300, 250)
    driver = _person(600, 120, 850, 380)
    phone_drv = _obj("phone", 700, 200, 760, 260)  # sürücü kutusunda
    dets = [passenger, driver, phone_drv]
    droi, pax, ip = dm.select_rois(dets, VEH, FRAME)
    st = dm.assess(None, dets, "normal", vehicle_bbox=VEH,
                   driver_bbox=droi, passenger_boxes=pax, driver_is_person=ip)
    assert st.phone_use is True
    assert "telefon_kullanimi" in assess_risk(st, speed_kmh=40, vtype="car").factors


def test_passenger_cigarette_does_not_set_smoking():
    """Yolcunun sigarası smoking bayrağını yakmamalı."""
    dm = DriverMonitor(mode="mock")
    passenger = _person(100, 20, 300, 250)
    driver = _person(600, 120, 850, 380)
    cig_pax = _obj("cigarette", 160, 90, 200, 120)
    dets = [passenger, driver, cig_pax]
    droi, pax, ip = dm.select_rois(dets, VEH, FRAME)
    st = dm.assess(None, dets, "normal", vehicle_bbox=VEH,
                   driver_bbox=droi, passenger_boxes=pax, driver_is_person=ip)
    assert st.smoking is False


def test_pedestrian_outside_vehicle_ignored():
    """Merkezi araç kutusu dışında kalan yaya sürücü/yolcu sayılmaz → geometrik yedek."""
    dm = DriverMonitor(mode="mock")
    pedestrian = _person(1100, 100, 1180, 380)  # araç (x2=1000) dışında
    droi, pax, is_person = dm.select_rois([pedestrian], VEH, FRAME)
    assert is_person is False                    # kabinde kişi yok
    assert pax == []
    assert droi is not None                       # geometrik sağ-yarı yedeği


def test_no_person_falls_back_to_geometric():
    """Hiç kişi yoksa geometrik sağ-yarı ROI'ye düşülür; belirsiz telefon konservatif."""
    dm = DriverMonitor(mode="mock")
    phone = _obj("phone", 700, 200, 760, 260)    # sağ yarıda
    droi, pax, is_person = dm.select_rois([phone], VEH, FRAME)
    assert is_person is False
    st = dm.assess(None, [phone], "normal", vehicle_bbox=VEH,
                   driver_bbox=droi, passenger_boxes=pax, driver_is_person=is_person)
    assert st.phone_use is True                   # yedek modda konservatif


def test_person_select_disabled_uses_geometric(monkeypatch):
    """driver_person_select=False → kişi olsa bile geometrik yarı-bölme kullanılır."""
    dm = DriverMonitor(mode="mock")
    monkeypatch.setattr(dm.s, "driver_person_select", False)
    driver = _person(600, 120, 850, 380)
    droi, pax, is_person = dm.select_rois([driver], VEH, FRAME)
    assert is_person is False
    assert pax == []
    # Geometrik sağ-yarı: x1 = mid_x = 500
    assert droi.x1 == 500


def test_ambiguous_phone_with_passengers_is_not_risk():
    """Yolcu varken hiçbir kişiyle örtüşmeyen telefon riske girmemeli (sürücü-dışı olabilir)."""
    dm = DriverMonitor(mode="mock")
    passenger = _person(100, 20, 300, 250)
    driver = _person(600, 120, 850, 380)
    phone_gap = _obj("phone", 400, 300, 440, 340)  # iki kişinin de dışında
    dets = [passenger, driver, phone_gap]
    droi, pax, ip = dm.select_rois(dets, VEH, FRAME)
    st = dm.assess(None, dets, "normal", vehicle_bbox=VEH,
                   driver_bbox=droi, passenger_boxes=pax, driver_is_person=ip)
    assert st.phone_use is False
    assert assess_risk(st, speed_kmh=40, vtype="car").score == 0
