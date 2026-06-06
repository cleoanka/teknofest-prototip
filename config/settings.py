"""
Merkezi yapılandırma.

ÖNEMLİ TASARIM NOTU
-------------------
Yarışma komitesi, 2. aşamada NİHAİ "etiket sınıfları" ve "çıktı formatını"
paylaşacağını belirtti (bkz. toplantı transkripti). Bu yüzden sınıf listesi ve
çıktı şeması burada TEK YERDEN yapılandırılabilir tutuldu; komite formatı
gelince yalnızca bu dosya ve ai/schema.py güncellenerek tüm sistem uyarlanır.

Sınıflar şartname (madde 4.4) + transkriptteki alt senaryolardan türetildi:
  araç plakası, araç içi nesneler, sürücü yorgunluğu, sigara/telefon kullanımı,
  yolcu (ön/arka koltuk), emniyet kemeri, kulaklık.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ──────────────────────────────────────────────────────────────────────────────
# Tespit sınıfları (komite formatı gelince güncellenecek tek nokta)
# ──────────────────────────────────────────────────────────────────────────────

# ─── Sınıf taksonomisi — İKİ AYRI uzay ───────────────────────────────────────
# (1) TARGET_CLASSES : MODELİN öğrendiği/çıkardığı sınıflar (data.yaml ile birebir).
#     Araç alt-tipleri AYRI tutulur (şartname: araç tipi ayrımı — minibüs vb.).
# (2) Şema/kanonik    : pipeline & backend'in gördüğü etiketler (vehicle, person, ...).
#     Araç alt-tipleri tek 'vehicle' etiketine toplanır; ham tip vehicle.vtype olur.
#     Böylece şema/backend kontratı (vehicle + vtype) hiç değişmez.

# (1) Modelin sınıfları — eğitim indeksleri / data.yaml 'names' ile birebir, sıralı.
TARGET_CLASSES = [
    "car",           # 0  ┐
    "minibus",       # 1  │ araç alt-tipleri (minibus COCO'da YOK → Türk verisinden)
    "bus",           # 2  │
    "truck",         # 3  │
    "motorcycle",    # 4  ┘
    "license_plate", # 5
    "person",        # 6  (yolcu / sürücü)
    "phone",         # 7
    "cigarette",     # 8
    "seatbelt",      # 9
    "headphone",     # 10
]

# Araç alt-tipleri: pipeline bunları tek 'vehicle' nesnesine toplar, tipi vtype'a yazar.
VEHICLE_TYPES = ("car", "minibus", "bus", "truck", "motorcycle")

# (2a) EĞİTİM verisi hazırlama: COCO kategori adı → TARGET_CLASSES adı (birleştirme YOK).
#      COCO car/truck/bus/motorcycle ayrı kalır; minibus COCO'da yok (Türk verisinden gelir).
COCO_TO_TARGET = {
    "car": "car",
    "truck": "truck",
    "bus": "bus",
    "motorcycle": "motorcycle",
    "person": "person",
    "cell phone": "phone",
}

# (2b) ÇIKARIM → şema: model/COCO sınıf adı → (şema_etiketi, vtype).
#      Araç alt-tipleri 'vehicle'a toplanır (vtype=ham tip); diğer sınıflar kendileri.
#      Hem fine-tune modelin (TARGET adları) hem stok COCO modelin (COCO adları) çıktısını karşılar.
CANONICAL_MAP = {
    "car":           ("vehicle", "car"),
    "minibus":       ("vehicle", "minibus"),
    "bus":           ("vehicle", "bus"),
    "truck":         ("vehicle", "truck"),
    "motorcycle":    ("vehicle", "motorcycle"),
    "person":        ("person", None),
    "phone":         ("phone", None),
    "cell phone":    ("phone", None),    # stok COCO adı
    "license_plate": ("license_plate", None),
    "cigarette":     ("cigarette", None),
    "seatbelt":      ("seatbelt", None),
    "headphone":     ("headphone", None),
}

# Araç sınıfları (ŞEMA seviyesi — hız/plaka bu nesneye bağlanır). Detector 'vehicle' üretir.
VEHICLE_CLASSES = {"vehicle"}

# Araç içi / sürücü-davranışı nesneleri
CABIN_OBJECT_CLASSES = {"phone", "cigarette", "seatbelt", "headphone", "person"}

# Sürücü durum bayrakları (pipeline tarafından üretilir)
DRIVER_STATE_FLAGS = ["fatigue", "phone_use", "smoking", "no_seatbelt", "headphone"]


# ──────────────────────────────────────────────────────────────────────────────
# Risk ağırlıkları (ÖTR Katkı: Risk Engine — şartname "risk teşkil eden durumlar")
# ──────────────────────────────────────────────────────────────────────────────
RISK_WEIGHTS = {
    "phone_use": 40,
    "fatigue": 30,
    "smoking": 20,
    "overspeed": 15,
    "no_seatbelt": 15,
    "zigzag": 10,
    "headphone": 5,
}
RISK_LEVELS = [(0, "LOW"), (30, "MEDIUM"), (60, "HIGH"), (85, "CRITICAL")]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # YZ modu
    ai_mode: str = Field(default="auto")  # auto | real | mock
    yolo_model_normal: str = Field(default="yolov8n.pt")
    yolo_model_critical: str = Field(default="yolov8s.pt")
    yolo_device: str = Field(default="auto")
    conf_normal: float = Field(default=0.35)
    conf_critical: float = Field(default=0.25)
    iou_nms: float = Field(default=0.45)

    # QoD tetik motoru (500 ms ihtiyaç-bazlı değerlendirme döngüsü)
    qod_eval_period_ms: int = Field(default=500)
    qod_bbox_growth_threshold: float = Field(default=0.18)   # A: yaklaşma
    qod_low_conf_threshold: float = Field(default=0.55)      # B: belirsizlik
    qod_ocr_conf_threshold: float = Field(default=0.75)      # C: plaka okunamadı
    qod_roi_line: float = Field(default=0.55)                # D: ROI çizgisi (kare yüksekliğinin oranı)
    qod_ambiguous_low: float = Field(default=0.40)           # E: sınır olasılık alt
    qod_ambiguous_high: float = Field(default=0.60)          # E: sınır olasılık üst
    qod_release_conf: float = Field(default=0.85)            # bırakma
    qod_max_session_s: float = Field(default=5.0)
    qod_consecutive_required: int = Field(default=2)         # iki ardışık pozitif

    # Mock CAMARA 5G simülatörü
    camara_qod_normal_mbps: int = Field(default=5)
    camara_qod_critical_mbps: int = Field(default=20)
    camara_network_latency_ms: int = Field(default=60)

    # CAMARA Gerçek API Geçiş Altyapısı (mock modda boş kalır)
    camara_mode: str = Field(default="mock")            # mock | real
    camara_base_url: str = Field(default="")            # Turkcell sandbox URL
    camara_client_id: str = Field(default="")
    camara_client_secret: str = Field(default="")

    # JWT RS256 (ÖTR: JWT RS256 + 100 req/dak)
    require_auth: bool = Field(default=False)           # True → Bearer token zorunlu
    jwt_ttl_s: int = Field(default=3600)                # Token geçerlilik süresi (s)
    jwt_private_key_path: str = Field(default="")       # PEM dosyası (boşsa her startup yeni anahtar)

    # Rate limiting (ÖTR: 100 req/dak per IP)
    rate_limit: int = Field(default=100)                # req/minute

    # WebSocket
    ws_max_frame_bytes: int = Field(default=5 * 1024 * 1024)  # 5 MB

    # Hız tahmini (kalibrasyonsuz bbox-alan modeli)
    speed_ppm_exponent: float = Field(default=0.65)
    speed_calibration_k: float = Field(default=900.0)        # saha kalibrasyonu ile ayarlanır
    speed_limit_kmh: float = Field(default=50.0)

    # Sunucu
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    db_path: str = Field(default="events.sqlite3")

    @property
    def project_root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@lru_cache
def get_settings() -> Settings:
    return Settings()
