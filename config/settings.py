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

# COCO sınıf adı  ->  bizim kanonik sınıfımız.
# Standart (eğitilmemiş) YOLOv8 COCO ile gelir; haritalama ile probleme uyarlıyoruz.
COCO_TO_CANONICAL = {
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "person": "person",
    "cell phone": "phone",
    # 'cigarette' COCO'da yok -> fine-tune ile eklenecek (training/data.yaml)
}

# Araç sınıfları (hız/plaka bu nesnelere bağlanır)
VEHICLE_CLASSES = {"vehicle"}

# Araç içi / sürücü-davranışı nesneleri
CABIN_OBJECT_CLASSES = {"phone", "cigarette", "seatbelt", "headphone", "person"}

# Sürücü durum bayrakları (pipeline tarafından üretilir)
DRIVER_STATE_FLAGS = ["fatigue", "phone_use", "smoking", "no_seatbelt", "headphone"]

# Nihai (fine-tune sonrası hedeflenen) sınıf listesi — training/data.yaml ile eşittir
TARGET_CLASSES = [
    "vehicle",        # 0
    "license_plate",  # 1
    "person",         # 2  (yolcu / sürücü)
    "phone",          # 3
    "cigarette",      # 4
    "seatbelt",       # 5
    "headphone",      # 6
]


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

    # ── MediaPipe Kabin Analizi (el-yüz yakınlık tabanlı davranış tespiti) ──
    # NEDEN: sigara/kulaklık COCO'da yok, telefon küçük/elle kapalı → YOLO kaçırır.
    # MediaPipe Hands el iskeleti ile davranışı nesneyi görmeden yakalar (sensör füzyonu).
    mp_hands_enabled: bool = Field(default=True)              # FPS düşükse False ile kapat
    mp_hand_detect_conf: float = Field(default=0.4)           # el tespiti min güven
    mp_hand_near_ear_ratio: float = Field(default=0.9)        # el-kulak eşiği (yüz genişliğine oran) → telefon/kulaklık
    mp_hand_near_mouth_ratio: float = Field(default=0.7)      # el-ağız eşiği (yüz genişliğine oran) → sigara
    mp_cabin_persist_frames: int = Field(default=3)           # kaç ardışık karede onaylanırsa pozitif (gürültü süzme)
    # Kabin crop ön-iyileştirme (loş otopark + küçük/uzak yüz için — gerçek test verisinde kanıtlandı)
    mp_enhance_enabled: bool = Field(default=True)            # crop'u MediaPipe'a vermeden önce iyileştir
    mp_enhance_dark_below: float = Field(default=90.0)        # crop ort. parlaklığı bu altındaysa gamma+CLAHE aydınlat
    mp_min_crop_px: int = Field(default=320)                  # crop genişliği bu altındaysa büyüt (MediaPipe iç küçültmede yüzü kaybetmesin)
    # Sürücü kimliği (geometrik yüz imzası — BİYOMETRİK kimlik DEĞİL, sürücü-değişti tespiti)
    driver_id_change_threshold: float = Field(default=0.18)   # imza farkı bu üstüyse "sürücü değişti"

    # ── Emniyet kemeri (MediaPipe Pose + çapraz şerit Canny/Hough heuristiği) ──
    # NEDEN: COCO'da kemer sınıfı yok, fine-tune gelene kadar köprü. Heuristic → muhafazakâr.
    seatbelt_enabled: bool = Field(default=True)              # FPS düşükse / yanlış pozitif çoksa False
    seatbelt_pose_conf: float = Field(default=0.4)            # MediaPipe Pose min tespit güveni
    seatbelt_min_visibility: float = Field(default=0.5)       # omuz/kalça görünürlük eşiği (altında karar verme)
    seatbelt_canny_low: int = Field(default=50)              # kenar tespiti alt eşik
    seatbelt_canny_high: int = Field(default=150)            # kenar tespiti üst eşik
    seatbelt_min_line_ratio: float = Field(default=0.45)      # kemer çizgisi min uzunluk / gövde köşegeni
    seatbelt_min_angle_deg: float = Field(default=25.0)       # çapraz şerit açı alt sınırı
    seatbelt_max_angle_deg: float = Field(default=65.0)       # çapraz şerit açı üst sınırı
    seatbelt_persist_frames: int = Field(default=5)           # kaç ardışık karede kemer görülmezse "yok" (muhafazakâr)

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
