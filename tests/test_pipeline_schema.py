import json
from ai.pipeline import Pipeline
from ai.schema import FrameResult


def test_pipeline_detects_vehicle_normal(synthetic_frame):
    pipe = Pipeline()
    res, ctx = pipe.process(synthetic_frame, critical=False)
    assert isinstance(res, FrameResult)
    assert res.mode == "NORMAL"
    assert res.vehicle.present is True
    assert res.vehicle.bbox is not None
    # Normal modda plaka okunmaz (hafif profil)
    assert res.vehicle.plate.text is None


def test_pipeline_reads_plate_in_critical(synthetic_frame):
    pipe = Pipeline()
    res, ctx = pipe.process(synthetic_frame, critical=True)
    assert res.mode == "CRITICAL"
    assert res.vehicle.present is True
    # Mock modda gerçek OCR çalışmaz — plaka alanları None olabilir (sahte plaka üretilmez)
    # Önemli olan: PlateResult nesnesi mevcut olmalı ve geçerli formatta olmalı
    assert res.vehicle.plate is not None
    assert isinstance(res.vehicle.plate.confidence, float)
    # Sürücü/yolcu ROI alanları kritik modda hesaplanır
    assert res.vehicle.driver_bbox is not None
    assert res.vehicle.passenger_bbox is not None


def test_output_json_under_3kb(synthetic_frame):
    """ÖTR hedefi: WS çıktısı <3 KB."""
    pipe = Pipeline()
    res, _ = pipe.process(synthetic_frame, critical=True)
    payload = json.dumps(res.model_dump()).encode()
    assert len(payload) < 3072


def test_trigger_context_fields(synthetic_frame):
    pipe = Pipeline()
    _, ctx = pipe.process(synthetic_frame, critical=False)
    assert ctx.vehicle_present is True
    assert 0.0 <= ctx.vehicle_norm_y2 <= 1.0
    assert ctx.vehicle_conf > 0.0


def test_vehicle_plate_pixel_width_field(synthetic_frame):
    """plate_pixel_width: mock LP'de None, gerçek LP'de float olmalı."""
    from ai.schema import Vehicle
    v = Vehicle()
    assert v.plate_pixel_width is None   # varsayılan None

    pipe = Pipeline()
    res, _ = pipe.process(synthetic_frame, critical=True)
    # Mock LP modda plate_pixel_width None beklenir (LP detect [] döner)
    assert res.vehicle.plate_pixel_width is None or isinstance(
        res.vehicle.plate_pixel_width, float
    )


def test_bbox_width_height_properties():
    """BBox.width ve BBox.height property'leri doğru hesaplamalı."""
    from ai.schema import BBox
    b = BBox(x1=100.0, y1=200.0, x2=400.0, y2=250.0)
    assert b.width == 300.0
    assert b.height == 50.0
    assert b.area == 15000.0
