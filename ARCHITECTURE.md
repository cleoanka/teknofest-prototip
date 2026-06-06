# ARCHITECTURE.md — Sistem Mimarisi

> **TEKNOFEST 2026 · 5G & Yapay Zeka ile Akıllı Yol Güvenliği**
> Son güncelleme: 2026-06-06 · Durum: Faz 3 tamamlandı (72.7 FPS, RTX 4070)

---

## 1. Tek Cümle Özet

Sabit bir yol kamerasından gelen canlı görüntüyü YZ hattıyla işleyen; tehlike anında
CAMARA QoD API'si ile 5G bant genişliğini 5 → 20 Mbps'e yükselten, tehlike geçince
geri düşüren — **ihtiyaç-bazlı, uçtan uca akıllı yol güvenliği sistemi.**

---

## 2. Yüksek Seviye Mimari

```
┌─────────────────────────────────────────────────────────────────────┐
│                         İSTEMCİ KATMANI                             │
│                                                                     │
│   ┌──────────────────────┐        ┌──────────────────────────────┐  │
│   │   Mobil Uygulama     │        │      Web Dashboard           │  │
│   │  React Native + Expo │        │   Vanilla JS + getUserMedia  │  │
│   │  iOS & Android       │        │   Güvenlik konsolu, overlay  │  │
│   └──────────┬───────────┘        └──────────────┬───────────────┘  │
└──────────────┼──────────────────────────────────┼───────────────────┘
               │  REST / WebSocket / HLS           │
               ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         BACKEND KATMANI                             │
│                                                                     │
│   FastAPI 0.115 + Uvicorn · async WebSocket · Pydantic şema        │
│                                                                     │
│   ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐    │
│   │  main.py    │  │ qod_manager  │  │  camara/               │    │
│   │  REST + WS  │  │ Tetik→CAMARA │  │  qod.py + numverif.py  │    │
│   │  uç noktalar│  │  köprüsü     │  │  (mock → gerçek API)   │    │
│   └──────┬──────┘  └──────┬───────┘  └────────────┬───────────┘    │
│          │                │                        │                │
│   ┌──────▼──────┐  ┌──────▼───────┐        ┌──────▼───────┐        │
│   │   db.py     │  │  frames.py   │        │  Turkcell    │        │
│   │   SQLite    │  │  base64→BGR  │        │  5G Şebekesi │        │
│   └─────────────┘  └──────┬───────┘        └──────────────┘        │
└──────────────────────────┼──────────────────────────────────────────┘
                           │  ham kare (numpy BGR)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          YZ KATMANI  (ai/)                          │
│                                                                     │
│   Pipeline.process(frame, critical) → (FrameResult, TriggerContext) │
│                                                                     │
│  ┌──────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │ detector.py  │  │tracking.py │  │  speed.py  │  │plate_ocr.py│  │
│  │ YOLOv8n/s    │  │ IOU takip  │  │ bbox-alan  │  │EasyOCR+    │  │
│  │ (gerçek/mock)│  │ track_id   │  │ hız tahmini│  │konsensüs   │  │
│  └──────┬───────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  │
│         └────────────────┴────────────────┴───────────────┘         │
│                                    │                                │
│  ┌──────────────┐  ┌───────────────▼──────┐  ┌────────────────┐    │
│  │driver_state  │  │     risk.py          │  │ qod_trigger.py │    │
│  │MediaPipe     │  │  Ağırlıklı 0–100     │  │  A–E koşul     │    │
│  │EAR/PERCLOS   │  │  skor motoru         │  │  motoru (%40   │    │
│  │telefon/sigara│  │                      │  │  kriter beyni) │    │
│  └──────────────┘  └──────────────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

**Temel tasarım ilkesi:** Edge cihaz yok. Tüm YZ çıkarımı backend GPU'da koşar
(macOS → MPS, NVIDIA → CUDA). Mobil ve web istemcisi yalnızca sonuç alır.

---

## 3. Senaryo Akışı (Uçtan Uca)

```
① SIM Doğrulama
   CAMARA Number Verification → SMS/OTP yok, sessiz şebeke doğrulaması
   └─ device_token + phone_number → {devicePhoneNumberVerified: true}

② Normal Mod   [varsayılan durum]
   480p · 5 Mbps · YOLOv8n · 7 fps
   └─ Araç varlığı izlenir, QoD tetik motoru 500 ms'de A–E kontrol eder

③ QoD Tetik   [ihtiyaç-bazlı karar]
   500 ms döngüde 5 koşuldan ≥1 pozitif + 2 ardışık teyit
   └─ CAMARA POST /qod/sessions → 20 Mbps, 5 s oturum

④ Kritik Mod  [yüksek çözünürlük analiz]
   1080p · 20 Mbps · YOLOv8s + EasyOCR + MediaPipe
   └─ Plaka, hız, telefon, yorgunluk, risk skoru → JSON < 3 KB → WS

⑤ Bırakma     [otomatik geri düşüş]
   güven > 0.85 | süre dolumu | araç ROI dışında
   └─ CAMARA DELETE /qod/sessions/{id} → bant 5 Mbps'e döner

⑥ Gösterim
   WebSocket → Mobil/Web · Riskli olaylar SQLite'a kaydedilir
```

---

## 4. YZ Çıkarım Hattı (Kritik Mod, Detay)

```
[5G Akışı 480p/1080p]
        │
        ▼
[Letterbox 416/640 + ROI crop]
        │
        ▼
[YOLOv8n/s → NMS(conf=0.25, iou=0.45) → ByteTrack-benzeri IOU takip]
        │
        ├─ Blok A │ Kabin ROI → class 67 (cep telefonu tespiti)
        │
        ├─ Blok B │ Yüz ROI → MediaPipe Face Mesh (468 landmark)
        │          │           EAR 8-frame pencere → PERCLOS → yorgunluk
        │
        ├─ Blok C │ Plaka ROI → adaptive Y-crop
        │          │            3 varyant (orijinal / keskinleştirilmiş / gri)
        │          │            → PaddleOCR + EasyOCR → konsensüs → plaka
        │
        └─ Blok D │ bbox^0.65 → PPM (piksel-per-metre)
                   │ max(Δmerkez, Δalan) → km/h hız tahmini
                   ▼
[QoD Tetik Motoru A–E] + [Risk: Tel(40)+Sig(20)+Yorg(30)+Hız(15)+Zigzag(10)]
                   │
                   ▼ JSON < 3 KB
           [WebSocket → Mobil UI]
```

**Fine-tune stratejisi:** COCO pretrained + 3 aşamalı transfer öğrenme.
TOGG seti gelene kadar BDD100K + mozaik augmentation, gece/yağmur sentetik.
TensorRT INT8 ile %20–35 gecikme azalması (mAP kaybı < 1.5 puan). Focal Loss γ=2.0, 70/15/15 video-bazlı bölümleme.

---

## 5. QoD Tetik Motoru (Özgün Katkı — %40 Kriter)

500 ms döngüde değerlendirilen 5 koşul; **iki ardışık pozitif**te QoD oturumu açılır:

```
A │ bbox alan büyümesi > eşik        →  araç yaklaşıyor
B │ araç tespit güveni < 0.55        →  hafif model belirsiz, yüksek çözünürlük gerek
C │ plaka ROI var, OCR güveni < 0.75 →  okuma için daha fazla piksel gerek
D │ araç ROI sınır çizgisini geçti   →  okuma menzilinde
E │ araç içi nesne 0.40–0.60 arasında→  sınır güven, kesin karar için yüksek bant

(A|B|C|D|E) ve 2 ardışık pozitif
    → CAMARA POST /qod/sessions  (20 Mbps, 5 s)

Bırakma koşulları:
    güven > 0.85  │  oturum süresi doldu  │  araç ROI dışında
    → CAMARA DELETE /qod/sessions/{id}
```

`bandwidth_efficiency = 1 − (kritik_döngü / toplam_döngü)`

0.82 = zamanın yalnızca %18'inde yüksek banttaydık. "Sürekli açık musluk" değil —
**ihtiyaç-bazlı bant yönetimi.** Şartname %40 kriterinin doğrudan karşılığı.

Hedef metrikler: QoD tetik isabeti ≥ %85 · yanlış tetik ≤ %10 · ortalama oturum ≤ 4 s · bant verimliliği ≥ %60.

---

## 6. Teknoloji Yığını

| Katman | Teknoloji | Versiyon | Görev |
|---|---|---|---|
| Mobil | React Native + Expo | SDK 51, TypeScript | Kamera, NumVerif, canlı sonuç ekranı |
| Web | Vanilla JS + getUserMedia | — | Güvenlik konsolu, bbox overlay, olay listesi |
| Backend | FastAPI + Uvicorn | 0.115 | REST + WebSocket + QoD yönetimi |
| Çıkarım | Ultralytics YOLOv8 | 8.4.60 | Araç + araç içi nesne tespiti |
| OCR | EasyOCR (+ PaddleOCR) | — | Plaka okuma, çok-varyant konsensüs |
| Sürücü | MediaPipe Face Mesh | — | EAR/PERCLOS, yorgunluk, 468 landmark |
| Hızlanma | CUDA (NVIDIA) / MPS (Apple) | torch 2.6.0+cu124 | GPU çıkarımı |
| 5G API | CAMARA QoD + Number Verification | mock→gerçek | Bant yönetimi + sessiz SIM doğrulama |
| Veri | SQLite | — | Olay kaydı (→ PostgreSQL taşınabilir) |
| Şema | Pydantic | v2 | YZ↔Backend tip-güvenli kontrat |

**Ölçülen performans:** yolov8n → **72.7 FPS** (RTX 4070 Laptop 8GB, imgsz 640).
Normal mod hedef > 25 FPS ✓

---

## 7. Proje Dizin Yapısı

```
teknofest-prototip/
│
├── ai/                          🤖 YZ çıkarım hattı
│   ├── detector.py                  YOLOv8 gerçek / MockDetector
│   ├── lp_detector.py               Plaka tespiti (HuggingFace + CV yedek)
│   ├── plate_ocr.py                 Çok-varyant OCR + konsensüs
│   ├── driver_state.py              MediaPipe EAR/PERCLOS + ROI ayrımı
│   ├── speed.py                     Kalibrasyonsuz bbox-alan hız tahmini
│   ├── risk.py                      Ağırlıklı 0–100 risk skoru
│   ├── tracking.py                  IOU takip, track_id, swerving
│   ├── qod_trigger.py               ← %40 kriter: A–E koşul motoru
│   ├── pipeline.py                  Uçtan uca orkestrasyon
│   ├── schema.py                    Backend kontrat şeması (< 3 KB JSON)
│   ├── AGENTS.md                    YZ kolu çalışma kuralları
│   ├── PROGRESS.md                  İlerleme günlüğü + karar kayıtları
│   ├── plan.md                      Model eğitim stratejisi
│   └── training/
│       ├── train.py                 Aşamalı müfredat + iki kademe + INT8
│       ├── prepare_dataset.py       COCO→YOLO dönüştürme, audit, sızıntı tespiti
│       ├── fetch_data.py            Açık kaynak manifest + indirme yardımcıları
│       └── sources.json             Veri kaynakları manifest
│
├── backend/                     ⚙️ API ve veri katmanı
│   ├── main.py                      Tüm REST + WebSocket uç noktaları
│   ├── qod_manager.py               Tetik motoru → CAMARA köprüsü
│   ├── db.py                        SQLite olay kaydı
│   ├── frames.py                    base64/JPEG → numpy BGR çözücü
│   └── camara/
│       ├── qod.py                   Mock CAMARA QoD API (→ gerçek ile değiştirilir)
│       └── number_verification.py   Mock CAMARA NumVerif (→ gerçek ile değiştirilir)
│
├── frontend/                    🖥️ Web konsolu
│   ├── index.html
│   ├── app.js                       Kamera + WebSocket + overlay
│   └── styles.css
│
├── mobile/                      📱 React Native uygulama
│   ├── App.tsx
│   └── src/
│       ├── screens/                 Login, Dashboard, EventDetail
│       └── api/                     Backend bağlantı katmanı
│
├── tests/                       🧪 73 pytest testi (mock modda, model gerekmez)
├── eval/                        📊 Normal vs Kritik doğruluk + bant verimliliği
├── tools/                       🔧 Video test aracı, duman testleri
├── docs/                        📄 Teknik dökümanlar
├── config/
│   └── settings.py                  Tüm eşik / sabit / model yolu (tek nokta)
├── run_dev.sh                   ⚡ macOS/Linux başlatıcı (start/stop/restart/models)
├── run_dev.ps1                  ⚡ Windows PowerShell başlatıcı
├── Makefile                     🛠️ install / run / test / eval / clean
└── requirements.txt
```

---

## 8. API Uç Noktaları

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/api/health` | GET | Sistem durumu, AI mode, model adı |
| `/api/events` | GET | Riskli olay listesi (SQLite) |
| `/api/vehicles` | GET | Plaka bazlı araç özeti |
| `/api/qod/status` | GET | Bant durumu + `bandwidth_efficiency` |
| `/api/test-video` | POST | Video dosyası YZ'den geçir |
| `/api/test-video/files` | GET | Mevcut test videoları |
| `/api/clear` | POST | Olay veritabanını sıfırla |
| `/camara/number-verification:verify` | POST | Sessiz SIM doğrulama |
| `/camara/qod/sessions` | POST | QoD oturumu aç (20 Mbps) |
| `/camara/qod/sessions/{id}` | DELETE | QoD oturumunu kapat (5 Mbps'e dön) |
| `/ws/ingest` | WS | Kare gönder → FrameResult al |
| `/ws/detections` | WS | Salt-okuma abone soketi (web/mobil) |

Swagger UI: `http://localhost:8000/docs`

---

## 9. Tasarım Kararları

**Mock-first (K4):** Her modül kütüphane yoksa mock'a düşer. `AI_MODE=auto` — ultralytics/easyocr/mediapipe
yoksa sistem çökmez, 73 test her ortamda yeşil kalır. Yeni modül eklerken aynı desen zorunlu.

**Config-first (K3):** Tüm eşik, sabit ve model yolu `config/settings.py`'de. Hardcode yok.
Tek bir değişiklik her yere yayılır.

**Sözleşme (K5):** `ai/schema.py` — `FrameResult`, `Detection`, `Vehicle`, `TriggerContext` —
YZ ile Backend arasında kırılamaz kontrattır. JSON çıktısı her koşulda < 3 KB.

**İki kademe model:** Normal modda `yolov8n` (hız öncelikli, 72.7 FPS), kritik modda `yolov8s`
(doğruluk öncelikli). GPU hızlandırma: NVIDIA → CUDA, Apple Silicon → MPS.

**Bant verimliliği:** `bandwidth_efficiency = 1 − (kritik_süre / toplam_süre)`.
Sürekli 20 Mbps değil — A–E koşul motorunun verdiği karara göre açılıp kapanan dinamik QoD.

---

## 10. Mock'tan Gerçeğe Geçiş Haritası

| Bileşen | Şu an | Gerçeğe geçiş |
|---|---|---|
| CAMARA QoD | `backend/camara/qod.py` mock | `base_url` + auth değişir, çağrı sözleşmesi aynı |
| Number Verification | `backend/camara/number_verification.py` mock | Turkcell endpoint'i — aynı imza |
| Model | COCO-pretrained yolov8n/s | `ai/training/train.py` ile TOGG verisi fine-tune |
| Veritabanı | SQLite | PostgreSQL — şema aynı, bağlantı dizgisi değişir |
| Medya | getUserMedia / video dosyası | Final'de Turkcell'in sağlayacağı canlı kamera API'si |
| Hız kalibrasyonu | bbox-alan tahmini | Saha referans ölçümüyle `speed_calibration_k` güncelleme |

---

## 11. Mevcut Durum (2026-06-06)

| Bileşen | Durum |
|---|---|
| YZ hattı (detector, tracking, speed, plate_ocr, driver_state, risk, qod_trigger, pipeline) | ✅ Hazır |
| Mock modda uçtan uca çalışma | ✅ 73 test yeşil |
| Windows + CUDA doğrulaması (RTX 4070 Laptop 8GB) | ✅ Tamamlandı |
| Gerçek YOLOv8 GPU çıkarımı — **72.7 FPS** (yolov8n, RTX 4070) | ✅ Tamamlandı |
| Eğitim/veri araçları (prepare_dataset, train, fetch_data) | ✅ Hazır |
| Gerçek plaka OCR (EasyOCR + GPU) | 🔄 Faz 4 |
| Sürücü davranışı gerçek test (MediaPipe) | 🔄 Faz 5 |
| Hız kalibrasyonu (saha referansı) | 🔄 Faz 6 |
| QoD eval kanıtı (Normal vs Kritik bant verimliliği raporu) | 🔄 Faz 7 |
| Fine-tune (TOGG/komite verisi) | ⏳ Faz 8 — veri gelince |

Detaylı ilerleme ve karar günlüğü: [`ai/PROGRESS.md`](ai/PROGRESS.md)
YZ kolu çalışma kuralları: [`ai/AGENTS.md`](ai/AGENTS.md)
