# Akıllı Yol Güvenliği — 5G & Yapay Zeka Prototipi

**TEKNOFEST 2026 · 5G & Yapay Zeka ile Akıllı Yol Güvenliği Yarışması (Turkcell)**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-purple)
![React Native](https://img.shields.io/badge/React%20Native-Expo-61DAFB?logo=react&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-248%20geçiyor-brightgreen)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![GPU](https://img.shields.io/badge/GPU-CUDA%20%7C%20MPS%20%7C%20CPU-green)
![5G](https://img.shields.io/badge/5G-CAMARA%20QoD-red)
![Lisans](https://img.shields.io/badge/Lisans-MIT-green)

Canlı video akışını yapay zeka ile işleyen, **yalnızca ihtiyaç anında** 5G CAMARA
**Quality on Demand (QoD)** API'siyle bant genişliğini yükselten ve sonuçları
mobil uygulama + güvenlik konsolu üzerinde anlık gösteren uçtan uca **çalışan prototip**.

Mimari üç bağımsız parçadan oluşur (şartname ile birebir):
**Mobil uygulama (ön yüz) ↔ Backend ↔ YZ çıkarım hattı**

> **Model durumu:** Sistem COCO ön-eğitimli YOLOv8 ile çalışır. Komite TOGG/etiketli
> veriyi paylaşınca `ai/training/` ile fine-tune edilir. Model kütüphanesi kurulu
> değilse sistem otomatik **MOCK** moda düşer — testler her ortamda yeşil kalır.

---

## Kol Rehberleri

| Kol | Rehber | Ne Anlatıyor |
|-----|--------|-------------|
| 🤖 **YZ** | [`docs/yz.md`](docs/yz.md) | YOLO, plaka OCR, hız tahmini, sürücü analizi |
| 🖥️ **API** | [`docs/api.md`](docs/api.md) | FastAPI, WebSocket, CAMARA entegrasyonu |
| 📱 **Mobil** | [`docs/mobil.md`](docs/mobil.md) | React Native, Expo, iOS & Android |
| 🔗 **Entegrasyon** | [`docs/entegrasyon.md`](docs/entegrasyon.md) | Test, web arayüzü, sistem bütünleştirme |
| 📝 **Rapor** | [`docs/rapor.md`](docs/rapor.md) | Yarışma kriterleri, sunum, demo senaryosu |
| 📖 **Genel** | [`docs/basics.md`](docs/basics.md) | Projeyi sıfırdan anlatan giriş rehberi |

> **Hiç bilmiyorum, nereden başlayayım?** → [`docs/basics.md`](docs/basics.md)

---

## Ne Yapıyor? (30 Saniye Özet)

```
📷 Kamera  ──kare──►  🖥️ Backend  ──kare──►  🤖 YZ (YOLO + OCR)
           ◄──sonuç──             ◄──sonuç──

Normal → Tehlike Tespit → 5G QoD API → Bant 5→20 Mbps → Kritik Analiz → Bant 20→5 Mbps
```

1. Kamera görüntüyü saniyede 7 kez backend'e gönderir
2. YZ araç, plaka, sürücü davranışı ve risk skorunu hesaplar
3. Tehlike varsa **CAMARA QoD** ile 5G bant genişliği **otomatik artırılır**
4. Tehlike geçince bant düşer — sürekli yüksek bant yok, sadece gerektiğinde

---

## Puanlama Kriterleri (Şartname Tablo 1)

| Kriter | Ağırlık | Karşılığı |
|--------|---------|-----------|
| YZ doğruluğu (araç, plaka, hız, araç içi nesne) | **%40** | `ai/pipeline.py` — YOLOv8 + OCR + MediaPipe + risk |
| 5G QoD — **yalnız ihtiyaç anında** bant yükseltme | **%40** | `ai/qod_trigger.py` (A–E koşul motoru) + `backend/qod_manager.py` |
| Mimari & modern pratikler | **%20** | Katmanlı mimari, tip-güvenli şema, 248 test, `ARCHITECTURE.md` |

---

## Hızlı Başlangıç

### 1 — Backend + Web Dashboard

**macOS / Linux:**
```bash
./run_dev.sh start    # arka planda başlat (önerilen)
./run_dev.sh stop     # durdur
./run_dev.sh restart  # yeniden başlat
./run_dev.sh status   # çalışıyor mu?
./run_dev.sh logs     # canlı log takibi
./run_dev.sh          # ön planda başlat
```

**Windows (PowerShell):**
```powershell
.\run_dev.ps1 start    # arka planda başlat
.\run_dev.ps1 stop     # durdur
.\run_dev.ps1 restart  # yeniden başlat
.\run_dev.ps1 status   # çalışıyor mu?
.\run_dev.ps1 logs     # canlı log takibi
.\run_dev.ps1          # ön planda başlat
```

> İlk çalıştırmada YZ modelleri internet'ten indirilir — birkaç dakika sürebilir.

Tarayıcıda `http://localhost:8000/` → Giriş Yap → **Kamerayı Başlat**.

Alternatif:

```bash
make install          # sanal ortam + paketler
make run              # sunucuyu başlat
```

### 2 — Mobil Uygulama (iOS & Android)

```bash
cd mobile
npm install
npx expo start        # QR kodu telefonla okut (Expo Go uygulaması gerekli)
```

> Giriş ekranında **Sunucu Adresi** kutusuna Mac/PC'nin LAN IP'sini gir:
> ```bash
> # macOS
> ipconfig getifaddr en0
> # Windows
> ipconfig   # IPv4 adresine bak
> # Örn: 192.168.1.35 → 192.168.1.35:8000
> ```

### 3 — Testler & Değerlendirme

```bash
make test             # 248 pytest testi (model gerektirmez, mock modda çalışır)
make eval             # sentetik veri + Normal/Kritik doğruluk raporu
```

---

## Mevcut Durum (2026-06-06)

| Bileşen | Durum |
|---------|-------|
| YZ hattı (detector, tracking, speed, plate_ocr, driver_state, risk, qod_trigger, pipeline) | ✅ Hazır |
| Mock modda uçtan uca çalışma | ✅ 248 test yeşil |
| Windows + CUDA doğrulaması (RTX 4070 Laptop) | ✅ Tamamlandı |
| Gerçek YOLOv8 GPU çıkarımı (**72.7 FPS** yolov8n, RTX 4070) | ✅ Tamamlandı |
| Eğitim/veri araçları (`prepare_dataset`, `train`, `fetch_data`) | ✅ Hazır |
| JWT RS256 kimlik doğrulama + rate limiting (100 req/dak) | ✅ Tamamlandı |
| Prometheus `/metrics` + Grafana hazır | ✅ Tamamlandı |
| Uçtan uca gecikme ölçümü (`total_latency_ms`) | ✅ Tamamlandı |
| Zengin API (statistics, vehicles/{plate}, events/{id}, export, heatmap) | ✅ Tamamlandı |
| Plaka OCR — çok-blok birleştirme + Tesseract yedek (v2.2) | ✅ Tamamlandı |
| Sigara tespiti — el-ağız heuristic (v2.2) | ✅ Tamamlandı |
| CAMARA env vars (mock→gerçek geçiş altyapısı) | ✅ Tamamlandı |
| Gerçek plaka OCR karanlık sahne iyileştirmesi | 🔄 Faz 4 |
| Sürücü davranışı gerçek test (MediaPipe sahne testi) | 🔄 Faz 5 |
| Hız kalibrasyonu (saha referansı) | 🔄 Faz 6 |
| QoD eval kanıtı (Normal vs Kritik bant verimliliği raporu) | 🔄 Faz 7 |
| Fine-tune (TOGG/komite verisi) | ⏳ Komiteye bağlı — Faz 8 |

Detaylı ilerleme ve karar günlüğü: [`ai/PROGRESS.md`](ai/PROGRESS.md)

---

## Senaryo Akışı (Uçtan Uca)

```
1. SIM Doğrulama    CAMARA Number Verification — SMS/kod yok, sessiz
        ↓
2. Normal Mod       480p · 5 Mbps · YOLOv8n · araç varlığı izlenir
        ↓
3. QoD Tetik        500ms döngüde A–E koşullarından 2 ardışık pozitif
        ↓
4. Kritik Mod       1080p · 20 Mbps · YOLOv8s + OCR + MediaPipe
                    Plaka, hız, telefon, yorgunluk, risk skoru
        ↓
5. Bırakma          Yüksek güven / süre dolumu / araç uzaklaştı
                    → CAMARA QoD DELETE → Bant 5 Mbps'e döner
        ↓
6. Gösterim         WebSocket → Mobil/Web · Olaylar SQLite'a kaydedilir
```

---

## Proje Yapısı

```
teknofest-prototip/
│
├── ai/                  🤖 YZ çıkarım hattı
│   ├── detector.py          YOLOv8 (gerçek) / mock dedektör
│   ├── lp_detector.py       Plaka tespiti (HuggingFace + CV fallback)
│   ├── plate_ocr.py         Plaka OCR + konsensüs (EasyOCR + Tesseract yedek)
│   ├── driver_state.py      MediaPipe EAR/PERCLOS + sürücü/yolcu ROI ayrımı
│   ├── speed.py             Kalibrasyonsuz bbox-tabanlı hız
│   ├── risk.py              Risk skor motoru (0–100)
│   ├── tracking.py          IOU takip (track_id, bbox büyüme, swerving)
│   ├── qod_trigger.py       ← %40 kriter çekirdeği: A–E koşul motoru
│   ├── pipeline.py          Uçtan uca orkestrasyon
│   ├── schema.py            Backend kontrat şeması
│   ├── AGENTS.md            YZ kolu çalışma kuralları
│   ├── PROGRESS.md          İlerleme günlüğü ve karar kayıtları
│   ├── plan.md              Model eğitim stratejisi
│   └── training/            Fine-tune sistemi
│       ├── train.py             Aşamalı müfredat + iki kademe + INT8 export
│       ├── prepare_dataset.py   COCO→YOLO dönüştürme, audit, sızıntı tespiti
│       ├── fetch_data.py        Açık kaynak manifest + indirme yardımcıları
│       ├── sources.json         9 kaynak bildirimi (veri manifesti)
│       └── data.yaml            7 sınıf yapılandırması
│
├── backend/             🖥️ FastAPI sunucu
│   ├── main.py              REST + WebSocket uç noktaları (v1.5)
│   ├── auth.py              JWT RS256 kimlik doğrulama
│   ├── metrics.py           Prometheus domain metrikleri
│   ├── qod_manager.py       Tetik motoru ↔ CAMARA köprüsü
│   ├── db.py                SQLite olay deposu
│   ├── frames.py            Kare çözümleme/kodlama
│   └── camara/              Mock QoD + Number Verification
│
├── frontend/            🌐 Web güvenlik konsolu
│   ├── index.html           Ana sayfa (swerving göstergesi dahil)
│   ├── app.js               Kamera + WebSocket + bbox renk kodlaması
│   └── styles.css           Tasarım
│
├── mobile/              📱 React Native / Expo (iOS & Android)
│   ├── App.tsx              Ana uygulama
│   └── src/
│       ├── screens/         Login, Dashboard, EventDetail ekranları
│       ├── api/client.ts    Backend bağlantısı
│       └── types.ts         TypeScript şeması
│
├── tools/               🔧 Yardımcı araçlar
│   ├── test_video.py        Video test CLI + annotated çıktı
│   ├── camera_client.py     Masaüstü kamera istemcisi
│   └── smoke_real_model.py  Gerçek model duman testi
│
├── tests/               ✅ 248 pytest testi (25 dosya, mock modda çalışır)
├── eval/                📊 Doğruluk değerlendirmesi
│   ├── evaluate.py          Normal vs Kritik + bant verimliliği
│   └── real_smoke.py        Gerçek-mod pipeline duman testi
│
├── mock/                🎭 Sentetik test verisi
├── changes/             📋 Değişiklik günlükleri
│   ├── changes.md           Versiyon geçmişi (v2.2'ye kadar)
│   └── next.md              Sıradaki görevler (kol sorumlusu özeti)
│
├── docs/                📚 Kol rehberleri
└── config/settings.py   ⚙️  Tüm parametreler tek yerden
```

---

## Yapılandırma

Tüm eşikler, sınıflar ve QoD parametreleri `config/settings.py` ve `.env` üzerinden:

```bash
cp .env.example .env
# .env içini ihtiyaca göre düzenle
```

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|---------|
| `AI_MODE` | `auto` | `real` / `mock` / `auto` |
| `YOLO_DEVICE` | `auto` | `auto` / `cpu` / `mps` / `cuda` |
| `CONF_NORMAL` | `0.35` | Normal mod tespit güven eşiği |
| `QOD_EVAL_PERIOD_MS` | `500` | QoD değerlendirme aralığı |
| `SPEED_CALIBRATION_K` | `900.0` | Hız kalibrasyon sabiti |
| `SPEED_LIMIT_KMH` | `50.0` | Hız aşımı eşiği |

---

## Gerçek Modele Geçiş

```bash
pip install ultralytics easyocr mediapipe huggingface_hub
```

`AI_MODE=auto` (varsayılan) ile sistem paketler kuruluysa otomatik gerçek modele geçer.

- **Mac Apple Silicon:** YOLO otomatik **MPS** hızlandırması kullanır
- **NVIDIA GPU:** CUDA otomatik seçilir (RTX 4060/4070/4090 test edildi)
- **Kütüphane eksikse:** İlgili modül mock'a nazikçe düşer, sistem çökmez (K4 kuralı)

---

## Video Test Aracı

Kamera olmadan doğrudan video dosyası üzerinde test:

```bash
# Basit test
python tools/test_video.py project-files/test-verisi/video_3.mp4

# Annotated çıktı + JSON raporu
python tools/test_video.py video.mp4 --scale 0.5 --every 2 \
    --out output/result.mp4 --json-out results.json

# Backend üzerinden (REST endpoint)
curl -X POST http://localhost:8000/api/test-video \
    -F "filename=video_3.mp4" -F "every_n=2" -F "scale=0.5"
```

---

## API Özeti

| Uç Nokta | Yöntem | Açıklama |
|----------|--------|---------|
| `/api/health` | GET | Sistem sağlık kontrolü |
| `/api/health/deep` | GET | Derin sağlık kontrolü (DB, pipeline, WS) |
| `/api/ping` | GET | Canlılık testi |
| `/api/version` | GET | Versiyon bilgisi |
| `/api/system/info` | GET | Süreç, bellek, uptime istatistikleri |
| `/api/events` | GET | Riskli olay listesi (filtreli, sayfalı) |
| `/api/events/summary` | GET | Olay özet istatistikleri |
| `/api/events/export` | GET | CSV dışa aktarım (plaka/seviye filtreli) |
| `/api/events/heatmap` | GET | Zaman bazlı yoğunluk haritası |
| `/api/events/{id}` | GET | Tek olay detayı |
| `/api/events/{id}` | DELETE | Tek olay sil |
| `/api/statistics` | GET | Son N saatin istatistikleri |
| `/api/vehicles` | GET | Plaka bazlı araç özeti |
| `/api/vehicles/{plate}` | GET | Plakaya göre olay geçmişi |
| `/api/vehicles/{plate}/timeline` | GET | Araç zaman çizelgesi |
| `/api/qod/status` | GET | Bant genişliği durumu + verimlilik |
| `/api/qod/proof` | GET | QoD tetik kanıtı raporu |
| `/api/settings` | GET | Çalışma zamanı ayarları |
| `/api/settings` | PATCH | Ayar güncelleme (AI_MODE vb.) |
| `/api/test-video` | POST | Video dosyası YZ'den geçir |
| `/api/test-video/files` | GET | Mevcut test videoları listele |
| `/api/clear` | POST | Olay veritabanını temizle |
| `/api/demo-token` | POST | Geliştirme JWT token'ı |
| `/.well-known/jwks.json` | GET | RS256 public key (JWKS) |
| `/camara/number-verification:verify` | POST | Sessiz SIM doğrulama → RS256 JWT |
| `/camara/qod/sessions` | GET | Aktif QoD oturumları |
| `/camara/qod/sessions` | POST | QoD oturumu aç (20 Mbps) |
| `/camara/qod/sessions/{id}` | GET | Oturum detayı |
| `/camara/qod/sessions/{id}` | DELETE | QoD oturumunu kapat |
| `/metrics` | GET | Prometheus metrikleri |
| `/ws/ingest` | WS | Kare gönder → sonuç al |
| `/ws/detections` | WS | Salt-okuma abone soketi |
| `/ws/status` | WS | Sistem durum soketi |

> Tüm `/api/*` ve `/camara/*` uç noktaları: **100 req/dak** rate limit · `Authorization: Bearer <JWT>` opsiyonel.

Swagger UI: [`http://localhost:8000/docs`](http://localhost:8000/docs)

---

## Sık Kullanılan Komutlar

```bash
# Sistem
./run_dev.sh              # Tam sistem başlat (macOS/Linux)
.\run_dev.ps1             # Tam sistem başlat (Windows)
make test                 # 248 testi çalıştır
make eval                 # Normal vs Kritik doğruluk raporu
make mock                 # Sentetik test videosu üret
make clean                # venv + cache + db temizle

# Sadece mock modda (YZ modeli olmadan):
AI_MODE=mock .venv/bin/python -m uvicorn backend.main:app --reload

# Gerçek model duman testi:
AI_MODE=real python -m eval.real_smoke
AI_MODE=real python -m tools.smoke_real_model

# Veri araçları:
python -m ai.training.fetch_data list
python -m ai.training.fetch_data coverage
python -m ai.training.prepare_dataset verify --data ai/training/data.yaml
python -m ai.training.train --tier critical --curriculum --dry-run
```

---

## Mimari Kararlar

- **Mock-first (K4):** Her modül kütüphane yoksa mock'a düşer, testler her ortamda yeşil kalır
- **Config-first (K3):** Tüm eşik ve sabitler `config/settings.py`'de, hardcode yok
- **Sözleşme (K5):** `ai/schema.py` YZ ↔ Backend kontratıdır, tek taraflı kırılmaz
- **İki kademe:** Normal modda `yolov8n` (hız), kritik modda `yolov8s` (doğruluk)
- **Bant verimliliği:** Sürekli açık musluk değil, A–E koşul motoruyla ihtiyaç-bazlı QoD

Detaylı mimari: [`ARCHITECTURE.md`](ARCHITECTURE.md) · Kol kuralları: [`/docs`](/docs)
