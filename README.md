# Akıllı Yol Güvenliği — 5G & Yapay Zeka Prototipi

**TEKNOFEST 2026 · 5G & Yapay Zeka ile Akıllı Yol Güvenliği Yarışması (Turkcell)**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-purple)
![React Native](https://img.shields.io/badge/React%20Native-Expo-61DAFB?logo=react&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-38%20geçiyor-brightgreen)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-lightgrey)
![5G](https://img.shields.io/badge/5G-CAMARA%20QoD-red)
![Lisans](https://img.shields.io/badge/Lisans-MIT-green)

Bu depo; canlı video akışını yapay zeka ile işleyen, **yalnızca ihtiyaç anında**
5G CAMARA **Quality on Demand (QoD)** API'siyle bant genişliğini yükselten ve
sonuçları mobil uygulama + güvenlik konsolu üzerinde gösteren uçtan uca bir
**çalışan prototiptir**. Mimari üç bağımsız parçadan oluşur (şartname/transkript
ile birebir): **Mobil uygulama (ön yüz) ↔ Backend ↔ YZ çıkarım hattı**.

> Eğitilmiş özel model henüz yok. Sistem standart (COCO ön-eğitimli) YOLOv8 ile
> çalışır; komite TOGG/etiketli veriyi paylaşınca `ai/training/` ile fine-tune
> edilir. Model kütüphanesi kurulu değilse sistem otomatik **MOCK** moda düşer,
> böylece her ortamda uçtan uca çalışır ve testler yeşil kalır.

---

## Kol Rehberleri (Yeni Başlayanlar Buradan)

Projeye yeni katıldıysan, koluna göre ilgili belgeyi oku:

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
|--------|---------|----------|
| YZ doğruluğu (araç, plaka, hız, araç içi nesne) | **%40** | `ai/pipeline.py` — YOLOv8 + OCR + MediaPipe + risk |
| 5G QoD — **yalnız ihtiyaç anında** bant yükseltme | **%40** | `ai/qod_trigger.py` (A–E koşul motoru) + `backend/qod_manager.py` |
| Mimari & modern pratikler | **%20** | Katmanlı mimari, tip-güvenli şema, 38 test, `ARCHITECTURE.md` |

---

## Hızlı Başlangıç

### 1 — Backend + Web Dashboard

```bash
./run_dev.sh          # venv kurar, bağımlılıkları indirir, sunucuyu başlatır
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

> Giriş ekranında **Sunucu Adresi** kutusuna Mac'in LAN IP'sini gir:
> ```bash
> ipconfig getifaddr en0   # örn: 192.168.1.35 → 192.168.1.35:8000
> ```

### 3 — Testler & Değerlendirme

```bash
make test             # 38 pytest testi (model gerektirmez, mock modda çalışır)
make eval             # sentetik veri + Normal/Kritik doğruluk raporu
```

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
│   ├── plate_ocr.py         Plaka OCR + konsensüs (EasyOCR)
│   ├── driver_state.py      MediaPipe EAR/PERCLOS + davranış
│   ├── speed.py             Kalibrasyonsuz bbox-tabanlı hız
│   ├── risk.py              Risk skor motoru (0–100)
│   ├── tracking.py          IOU takip (track_id, bbox büyüme)
│   ├── qod_trigger.py       ← %40 kriter çekirdeği: A–E koşul motoru
│   ├── pipeline.py          Uçtan uca orkestrasyon
│   └── training/            Fine-tune sistemi
│
├── backend/             🖥️ FastAPI sunucu
│   ├── main.py              REST + WebSocket uç noktaları
│   ├── qod_manager.py       Tetik motoru ↔ CAMARA köprüsü
│   ├── db.py                SQLite olay deposu
│   └── camara/              Mock QoD + Number Verification
│
├── frontend/            🌐 Web güvenlik konsolu
├── mobile/              📱 React Native / Expo (iOS & Android)
├── tests/               ✅ 38 pytest testi
├── eval/                📊 Doğruluk değerlendirmesi
├── mock/                🎭 Sentetik test verisi
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
| `CONF_NORMAL` | `0.35` | Normal mod tespit güven eşiği |
| `QOD_EVAL_PERIOD_MS` | `500` | QoD değerlendirme aralığı |
| `SPEED_CALIBRATION_K` | `900.0` | Hız kalibrasyon sabiti |
| `SPEED_LIMIT_KMH` | `50.0` | Hız aşımı eşiği |

---

## Gerçek Modele Geçiş

```bash
pip install ultralytics easyocr mediapipe
```

`AI_MODE=auto` (varsayılan) ile sistem paketler kuruluysa otomatik gerçek modele geçer.
Mac Apple Silicon'da YOLO otomatik **MPS** hızlandırması kullanır.

---

## API Özeti

| Uç Nokta | Yöntem | Açıklama |
|----------|--------|---------|
| `/api/health` | GET | Sistem sağlık kontrolü |
| `/api/events` | GET | Riskli olay listesi |
| `/api/qod/status` | GET | Bant genişliği durumu |
| `/camara/number-verification:verify` | POST | Sessiz SIM doğrulama |
| `/camara/qod/sessions` | POST | QoD oturumu aç |
| `/camara/qod/sessions/{id}` | DELETE | QoD oturumunu kapat |
| `/ws/ingest` | WS | Kare gönder → sonuç al |
| `/ws/detections` | WS | Salt-okuma abone soketi |

Tüm uç noktaları tarayıcıdan dene: [`http://localhost:8000/docs`](http://localhost:8000/docs)

---

## Sık Kullanılan Komutlar

```bash
./run_dev.sh          # Tam sistem başlat
make test             # Tüm testleri çalıştır
make eval             # Doğruluk raporu
make mock             # Sentetik test videosu üret
make clean            # venv + cache + db temizle

# Sadece mock modda (YZ modeli olmadan):
AI_MODE=mock .venv/bin/python -m uvicorn backend.main:app --reload
```

---

Detaylı mimari: [`ARCHITECTURE.md`](ARCHITECTURE.md) · Kol rehberleri: [`docs/`](docs/)
