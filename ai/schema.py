"""
Çıktı şeması — backend'in mobil/dashboard'a WS üzerinden yolladığı JSON (<3 KB).

Bu şema, komitenin paylaşacağı "çıktı formatı" gelince kolayca uyarlanabilecek
şekilde tek dosyada toplandı. Tüm alanlar Teknofest senaryosuna (araç + plaka +
gerçek hız + araç içi nesne + sürücü davranışı + risk) karşılık gelir.
"""
from __future__ import annotations

from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field


Mode = Literal["NORMAL", "CRITICAL"]


class BBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2


class Detection(BaseModel):
    label: str                       # kanonik sınıf (vehicle, person, phone, ...)
    confidence: float
    bbox: BBox
    track_id: Optional[int] = None
    attributes: Dict[str, str] = Field(default_factory=dict)  # ör. {"color": "white"}


class PlateResult(BaseModel):
    text: Optional[str] = None
    confidence: float = 0.0
    valid_format: bool = False       # TR plaka formatına uyuyor mu


class DriverState(BaseModel):
    fatigue: bool = False
    ear: Optional[float] = None      # Eye Aspect Ratio
    perclos: Optional[float] = None  # % göz kapalı oranı
    phone_use: bool = False          # Yalnızca SÜRÜCÜ tarafında
    smoking: bool = False
    no_seatbelt: bool = False
    headphone: bool = False
    passenger_phone: bool = False    # Yolcu tarafında telefon (tehlike sayılmaz)


class Vehicle(BaseModel):
    present: bool = False
    track_id: Optional[int] = None
    vtype: Optional[str] = None      # car/truck/bus... (alt tip)
    color: Optional[str] = None
    plate: PlateResult = Field(default_factory=PlateResult)
    speed_kmh: Optional[float] = None
    # Hız gerçek metrik km/h mi (oto-kalibrasyon kuruldu) yoksa kalibrasyonsuz
    # göreceli sezgisel mi? (gercek_hiz_plani.md §7.4 — raporlamada karışmasın)
    speed_is_calibrated: bool = False
    bbox: Optional[BBox] = None
    plate_bbox: Optional[BBox] = None          # Plaka kutusu (sarı)
    plate_pixel_width: Optional[float] = None  # px genişlik — mesafe kalibrasyonu (52cm / px_w)
    driver_bbox: Optional[BBox] = None         # Sürücü tarafı ROI (mavi)
    passenger_bbox: Optional[BBox] = None      # Yolcu tarafı ROI (turuncu)
    swerving: bool = False                     # Zigzag/şerit ihlali


class RiskAssessment(BaseModel):
    score: int = 0
    level: str = "LOW"               # LOW | MEDIUM | HIGH | CRITICAL
    factors: List[str] = Field(default_factory=list)


class QoDStatus(BaseModel):
    mode: Mode = "NORMAL"
    bandwidth_mbps: int = 5
    active_session_id: Optional[str] = None
    last_trigger_reason: Optional[str] = None   # A|B|C|D|E açıklaması
    session_age_s: float = 0.0


class FrameResult(BaseModel):
    """WS /ws/detections üzerinden yayınlanan ana mesaj."""
    frame_id: int
    ts: float                        # epoch seconds
    mode: Mode = "NORMAL"
    model_profile: str = "yolov8n"
    detections: List[Detection] = Field(default_factory=list)
    vehicle: Vehicle = Field(default_factory=Vehicle)
    driver: DriverState = Field(default_factory=DriverState)
    risk: RiskAssessment = Field(default_factory=RiskAssessment)
    qod: QoDStatus = Field(default_factory=QoDStatus)
    latency_ms: float = 0.0          # YZ pipeline çıkarım süresi (ms)
    total_latency_ms: float = 0.0    # Uçtan uca gecikme — client_ts varsa ağ dahil (ms)
    fps: float = 0.0


class EventRecord(BaseModel):
    """SQLite'a yazılan ve /api/events ile dönen kalıcı olay."""
    id: Optional[int] = None
    ts: float
    plate: Optional[str] = None
    vtype: Optional[str] = None
    speed_kmh: Optional[float] = None
    risk_score: int = 0
    risk_level: str = "LOW"
    factors: str = ""                # virgülle ayrık
    mode: str = "NORMAL"
    snapshot: Optional[str] = None   # base64 küçük resim (ops.)
