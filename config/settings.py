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
from typing import Dict, Optional
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
    "harsh_braking": 35,   # ani fren / olası kaza — yüksek ağırlık (kaza sonrası zincirleme risk)
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

    # ── Sürücü davranışı — MediaPipe el-yüz geometrisi (ai/driver_state.py) ──
    # NEDEN: COCO sigara/kulaklık sınıfını bilmez, telefonu da araç-içi küçük
    # nesne olarak güvenilmez yakalar. Bu yüzden telefon/sigara/kulaklık,
    # MediaPipe Hands (el landmark'ı) + FaceMesh (kulak/ağız) GEOMETRİSİNDEN
    # çıkarılır: el kulağa yakınsa telefon, parmak ağıza yakınsa sigara.
    # Mesafeler YÜZ GENİŞLİĞİNE oranlanır → ölçek-bağımsız (yakın/uzak yüz fark etmez).
    driver_mp_hands: bool = Field(default=True)            # MediaPipe Hands aç/kapa
    # Algılama güvenleri DÜŞÜK tutulur: dış kamerada sürücü karanlık/uzak/profil →
    # yüksek eşik yüzü/eli hiç bulamıyordu (recall darboğazı). Düşürmek recall'ı artırır.
    driver_hand_conf: float = Field(default=0.3)           # Hands min algılama/takip güveni
    driver_face_conf: float = Field(default=0.3)           # FaceMesh min algılama/takip güveni
    # el-kulak < ratio×yüz_gen → telefon adayı. ÖLÇÜM (sweep): gerçek telefonda el
    # kulağa ÇOK yakın (video_2 d_ear %99'u <0.40×fw), FP'de dağınık (video_1 %53).
    # 0.60→0.40: video_1 telefon FP %13→%0 silinir, video_2 %61 korunur. 0.40 altı
    # ek fayda yok; 0.25 video_2'yi düşürmeye başlar → 0.40 doğrulanmış eşik.
    driver_phone_ear_ratio: float = Field(default=0.40)
    driver_smoke_mouth_ratio: float = Field(default=0.45)  # parmak-ağız < 0.45×yüz_gen → sigara adayı
    driver_state_window: int = Field(default=15)           # sürdürme/tekrar penceresi (kare) ~0.5sn@30fps
    driver_phone_sustain: int = Field(default=5)           # pencerede ≥N kare el-kulakta → phone_use teyit
    driver_smoke_sustain: int = Field(default=5)           # pencerede ≥N kare parmak-ağızda → smoking teyit
    # Latch (süregelen davranış kilidi): telefon/sigara bir kez TEYİT edilince bayrağı
    # bu kadar kare basılı tut. Sürücü uzaklaşıp birkaç karede el/yüz kaybolsa da
    # davranış sürdüğünden bayrak düşmez → tutarlı çıktı. Sustain teyidi şart olduğundan
    # tek-kare FP latch'lenmez (gürültüye karşı güvenli). ~0.9 sn @50fps. 0 = kapalı.
    driver_latch_frames: int = Field(default=45)
    # Kulaklık: saf landmark kulaklığı GÖREMEZ (ele bağlı değil). Düşük-güvenli
    # "el sabit kulakta ama telefon teyidi yok" sezgisi opsiyonel; varsayılan KAPALI
    # (Adım 6 / fine-tune yol haritası madde 7'ye bırakıldı).
    driver_headphone_enable: bool = Field(default=False)
    # Sürücü ROI ön-işleme — dış sabit kamerada sürücü UZAK + KARANLIK olur
    # (kapalı otopark senaryosu). MediaPipe küçük/loş yüzü göremez; ROI kırpıldıktan
    # sonra hedef boya BÜYÜTÜLÜR ve gamma+CLAHE ile PARLATILIR. Mesafe eşikleri
    # yüz-genişliği ORANI olduğundan büyütme oranları bozmaz (ölçek-bağımsız).
    driver_roi_min_px: int = Field(default=320)        # ROI kısa kenarı bu px'e büyütülür
    driver_roi_max_upscale: float = Field(default=4.0) # aşırı büyütme/bulanıklık sınırı
    driver_roi_brighten: bool = Field(default=True)    # düşük ışık: gamma + CLAHE
    driver_roi_gamma: float = Field(default=1.8)       # >1 gölgeleri açar
    # NATIVE (büyütme öncesi) yüz genişliği bu px'in altındaysa araç UZAK/yüz KÜÇÜK
    # demektir → el-parmak landmark'ları gürültülü → telefon/sigara geometrisi BASTIRILIR
    # (uzak mesafe yanlış pozitifini önler). Tek videoya özel değil, genel ilke.
    # ÖLÇÜM (grid): 45→30 video_1 sigara recall %32→%59'a çıkar; video_2/video_3
    # sigara %0 kalır (FP yok), telefon/yorgunluk bozulmaz. 30 altı ek fayda vermez
    # (kalan tavan el algılama). Bu yüzden 30 = doğrulanmış tatlı nokta.
    driver_min_face_px: int = Field(default=30)
    # Yüz konum cache'i: dış sabit kamerada FaceMesh kareleri seyrek yakalar
    # (ölçüm: video_1 yüz %30, el %54). Kafa direksiyon başında ~sabit olduğundan
    # son bilinen ağız/kulak konumu (normalize) N kare saklanır; yüz kaybolduğu ama
    # ELİN bulunduğu karelerde sigara/telefon geometrisi yine de hesaplanır → recall
    # tavanı %30'dan el oranına (%54) doğru açılır. Göreli (ağız-vs-kulak) test +
    # sustain + latch FP'yi frenler. ~3 sn @10fps. 0 = kapalı (yalnız gerçek yüz).
    driver_face_cache_frames: int = Field(default=30)
    # Parlak-piksel CV sigara yedeği: ağız üstü ince parlak nesne arar. Gerçek
    # footage'ta (ön cam yansıması, far, kontrast) yanlış pozitifi yüksek →
    # varsayılan KAPALI. Asıl sigara sinyali el-parmak↔ağız geometrisi.
    driver_smoke_brightpixel: bool = Field(default=False)
    # ── Sürücü seçimi: kişi-bazlı (geometrik yarı-bölme yerine) ──
    # NEDEN: Aracı statik olarak sağ/sol yarıya bölmek yolcu ile sürücüyü ayırt
    # edemiyordu (yolcu sağ yarıya, sürücü sol yarıya taşabilir). Artık araç
    # kabinindeki 'person' tespitleri arasından KAMERANIN BAKIŞ AÇISINA göre
    # EN SAĞ-ALTTAKİ kişi sürücü, kalan kişiler yolcu sayılır. Yalnızca SÜRÜCÜ
    # kişinin kutusuna düşen ihlaller (telefon/sigara/kulaklık) ve sürücü kutusu
    # üzerinde çalışan MediaPipe geometrisi risk skoruna etki eder; yolcuların
    # hareketleri risk DIŞIDIR. 'person' tespiti yoksa geometrik yarı-ROI'ye düşülür.
    driver_person_select: bool = Field(default=True)
    # "Sağ-alt" skoru: score = right_w*(x2/W) + bottom_w*(y2/H); en yüksek = sürücü.
    # Ağırlıklar açıya göre ayarlanabilir (ör. tam profilde sağ baskın → right_w↑).
    driver_select_right_weight: float = Field(default=1.0)
    driver_select_bottom_weight: float = Field(default=1.0)

    # Çoklu nesne takipçisi (real mod)
    # bytetrack → YOLOv8 dahili ByteTrack (hızlı, kamera hareketi yok)
    # botsort   → BoT-SORT (kamera titremesine dayanıklı, ReID opsiyonel)
    # iou       → saf IOU tracker (dahili, ByteTrack/BoT-SORT gerekmez)
    tracker_type: str = Field(default="bytetrack")

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
    speed_limit_kmh: float = Field(default=50.0)             # vtype haritada karşılığı yoksa yedek
    # Araç tipine göre dinamik hız limiti (TR trafik mevzuatı genel sınırlar) — risk skoru bunu kullanır
    speed_limit_by_vtype: Dict[str, float] = Field(
        default_factory=lambda: {"car": 120.0, "minibus": 100.0, "bus": 100.0,
                                 "truck": 90.0, "motorcycle": 120.0})

    # Plaka YOLO dedektörü
    lp_model_path: str = Field(default="")        # LP_MODEL_PATH → yerel .pt yolu (öncelik 1)
    lp_hf_download: bool = Field(default=False)   # LP_HF_DOWNLOAD → eski opt-in bayrağı (geriye uyum)
    # Otomatik indirme: model yoksa ilk gerçek koşumda HuggingFace'den çek ve önbelleğe al.
    # Varsayılan AÇIK — CV fallback trafik levhasını plaka sanıyordu; gerçek model şart.
    # Mock/CI (LP_MOCK=1) bu yola hiç girmez → ağ/model gerekmez (K4 korunur).
    lp_auto_download: bool = Field(default=True)  # LP_AUTO_DOWNLOAD=0 ile kapatılır
    # İndirilecek model (tek-sınıf license_plate; ultralytics ile yüklenir, ~5-6 MB).
    lp_model_repo: str = Field(default="morsetechlab/yolov11-license-plate-detection")
    lp_model_file: str = Field(default="license-plate-finetune-v1n.pt")
    lp_conf: float = Field(default=0.25)          # YOLO eşiği (araç crop'unda makul precision)
    lp_mock: bool = Field(default=False)          # LP_MOCK → CI/test için LP atla

    # Plaka crop "siyah çerçeveyi takip et" katmanı (ai/plate_crop.py)
    plate_refine_crop: bool = Field(default=True)     # ROI içinde plaka çerçevesine sıkılaştır
    plate_deskew: bool = Field(default=True)          # belirgin eğikse düzleştir
    plate_min_likeness_std: float = Field(default=18.0)   # plaka-benzerlik: min kontrast (std, boyut-adaptif)
    plate_min_edge_density: float = Field(default=0.04)   # plaka-benzerlik: min dikey kenar yoğunluğu (boyut-adaptif)
    # LP model confidence bu değerin üzerindeyse looks_like_plate gate'i atlanır.
    # Model zaten yüksek güvenle tespit ettiyse küçük/uzak plakaların eşiklerini zorlaştırma.
    plate_lp_conf_bypass: float = Field(default=0.30)
    plate_track_ttl_frames: int = Field(default=75)       # araç kaybolunca plaka durumu ttl'i (75→1.5s@50fps)

    # Türk plakası fiziksel boyutları — mesafe kalibrasyonu için sabit (mm)
    plate_real_width_mm: float = Field(default=520.0)   # standart araç plakası
    plate_real_height_mm: float = Field(default=112.0)

    # ── Metrik hız oto-kalibrasyonu (gercek_hiz_plani.md) ──────────────────────
    # Referans fiziksel ölçüler (sahneden ppm türetmek için)
    plate_width_m: float = Field(default=0.520)              # TR Tip-1 plaka standardı (520 mm)
    # Sınıf-bazlı tipik araç genişliği (m) — plaka yokken ppm yedeği (Aşama 2)
    vehicle_width_m: Dict[str, float] = Field(
        default_factory=lambda: {"car": 1.80, "minibus": 2.00, "van": 2.00,
                                 "truck": 2.50, "bus": 2.50, "motorcycle": 0.80})
    lane_width_m: float = Field(default=3.50)                # TR şerit genişliği (Aşama 4)
    dash_pitch_m: float = Field(default=12.0)               # otoyol kesik çizgi adımı 4.5+7.5 (Aşama 4)
    # ppm(y) ölçek-alanı + hız hesabı parametreleri
    calib_min_samples: int = Field(default=6)               # ppm(y) regresyonu için min ölçüm
    plate_aspect_tolerance: float = Field(default=0.35)     # 520/120≈4.33'ten sapma toleransı (foreshortening)
    vehicle_ppm_weight: float = Field(default=0.25)         # araç-genişliği ppm örnek ağırlığı (plaka=1.0)
    speed_window_frames: int = Field(default=6)             # hız regresyon penceresi (Aşama 3)
    speed_max_accel_mps2: float = Field(default=8.0)        # fiziksel-olmayan ivme reddi (Aşama 3)
    speed_ema_alpha: float = Field(default=0.4)             # EMA alfa (geriye uyum; Kalman Q/R tercih edilir)
    speed_kalman_q: float = Field(default=3.0)              # Kalman süreç gürültüsü (hız değişim hızı)
    speed_kalman_r: float = Field(default=8.0)              # Kalman ölçüm gürültüsü (BEV hız belirsizliği)
    speed_scale_check_factor: float = Field(default=1.8)    # homografi↔plaka ölçek ayrışma eşiği (Problem 2: yol-tipi çapraz-kontrolü)
    speed_metric_max_kmh: float = Field(default=200.0)      # akıl sağlığı üst sınırı
    # Radar/ANPR mantığı: araç kadraj kenarına değdiğinde (kırpılma + homografi
    # ekstrapolasyonu nedeniyle ölçüm güvenilmez) o kare için hız hesaplanmaz;
    # son geçerli ölçüm "mühürlenip" gösterilmeye devam eder. Oran tabanlı —
    # 3840x2160'ta %1.5 ≈ 58x32px ölü bölge; farklı çözünürlüklerde tutarlı kalır.
    speed_edge_margin_pct: float = Field(default=0.015)
    # Ani fren / olası kaza tespiti: ~1 sn'lik pencerede hız düşüşü eşiği aşılırsa
    # (ör. 100→20 km/h) hem risk skoruna "ani_fren" faktörü eklenir hem QoD motoru
    # tetiklenir (5G bant genişliği acil-durum moduna geçer).
    harsh_braking_window_s: float = Field(default=0.8)       # bakılacak geçmiş penceresi (s)
    harsh_braking_decel_kmh_s: float = Field(default=-50.0)  # eşik: km/h kaybı / saniye (negatif=yavaşlama)
    # Aşama 4 — otomatik şerit homografisi (best-effort; VARSAYILAN KAPALI, cv2 ister)
    homography_auto: bool = Field(default=False)            # açıksa kareden şerit→homografi dene
    homography_calib_interval: int = Field(default=30)      # her N karede bir kalibrasyon denemesi
    # ── Plaka düzlemsel PnP (Katman 2 — foreshortening-bağımsız ölçek) ──────────
    # 4 plaka köşesi + bilinen 520×112 mm + odak uzaklığından plakanın metrik
    # derinliğini (Z) ve açısını çöz; eğik plakada bile doğru ppm = focal/Z üretir.
    # plate_corners (perspektif düzeltme) varsa observe_plate yerine bu kullanılır.
    plate_pnp_enabled: bool = Field(default=True)
    # Kamera odağı (px). None → yatay FOV varsayımından kare genişliğiyle tahmin edilir.
    camera_focal_px: Optional[float] = Field(default=None)
    camera_hfov_deg: float = Field(default=55.0)            # focal tahmini için tipik trafik kamerası HFOV
    plate_pnp_weight: float = Field(default=1.2)            # PnP ppm örnek ağırlığı (düz plaka=1.0'dan yüksek: açıdan bağımsız)
    plate_pnp_max_reproj_px: float = Field(default=6.0)    # köşe geri-izdüşüm RMS hatası üst sınırı (güven geçidi)
    plate_pnp_min_distance_m: float = Field(default=1.0)   # makul mesafe alt sınırı
    plate_pnp_max_distance_m: float = Field(default=120.0) # makul mesafe üst sınırı
    plate_pnp_max_tilt_deg: float = Field(default=60.0)    # bu açının üstündeki plaka pozu güvenilmez sayılır

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
