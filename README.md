# Akıllı Yol Güvenliği — 5G & Yapay Zeka Prototipi

**TEKNOFEST 2026 · 5G & Yapay Zeka ile Akıllı Yol Güvenliği Yarışması (Turkcell)**

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

## Puanlama kriterleriyle eşleşme (şartname Tablo 1)

| Kriter | Ağırlık | Bu projede karşılığı |
|---|---|---|
| YZ analizi doğruluk/hassasiyet (araç, plaka, gerçek hız, araç içi nesne) | **%40** | `ai/pipeline.py` — YOLOv8 + OCR + MediaPipe + hız + risk; Normal/Kritik profil. `eval/evaluate.py` doğruluğu ölçer. |
| 5G QoD API entegrasyonu — **yalnız ihtiyaç anında** bant yükseltme | **%40** | `ai/qod_trigger.py` (500ms, A–E koşul motoru) + `backend/qod_manager.py` + mock CAMARA QoD/NumVerif. Bant verimliliği raporlanır. |
| Yazılım mimarisi & modern pratikler (rapor/sunum) | **%20** | Katmanlı mimari, tip-güvenli şema, test paketi, `ARCHITECTURE.md`. |

---

## Hızlı başlangıç

### 1) Backend + Web Dashboard
```bash
cd teknofest-prototip
chmod +x run_dev.sh && ./run_dev.sh         # venv kurar, bağımlılıkları indirir, sunucuyu açar
# veya:  make install && make run
```
Tarayıcıda **http://localhost:8000/** → sessiz SIM doğrulama → "Kamerayı Başlat".
Mac dahili kamera veya **iPhone** (Continuity / Safari) kamerası kullanılabilir.

### 2) Mobil uygulama (Expo — ana ön yüz)
```bash
cd mobile && npm install
# src/api/client.ts -> API_BASE'i Mac LAN IP'sine ayarla (ipconfig getifaddr en0)
npx expo start            # iPhone'da Expo Go ile QR okut
```

### 3) Testler ve değerlendirme
```bash
make test                 # 38 test (mock modda deterministik)
make eval                 # mock veri üretir + Normal vs Kritik doğruluk karşılaştırır
```

---

## Senaryo akışı (uçtan uca)

1. **Sessiz giriş** — Mobil/konsol, CAMARA **Number Verification** ile SIM↔numara
   eşleşmesini şebekeye doğrulatır (SMS/kod yok).
2. **Normal mod** — Kamera 480p akar; hafif model (`yolov8n`) yalnız **araç varlığı,
   bbox büyümesi ve güven** izler. Bant düşük tutulur.
3. **QoD tetik** — 500 ms döngüde A–E koşullarından ikisi ardışık pozitif olunca
   **CAMARA QoD** ile yüksek bant (5→20 Mbps) talep edilir, akış 1080p'ye geçer,
   **ağır model** (`yolov8s` + OCR + MediaPipe) devreye girer.
4. **Kritik mod** — Plaka OCR, gerçek hız, araç içi nesne, sürücü davranışı
   (yorgunluk/telefon/sigara/kemer) tespit edilir, **risk skoru** üretilir.
5. **Bırakma** — Yüksek güven / süre dolumu / araç ROI dışına çıkınca QoD oturumu
   `DELETE` edilir, sistem Normal'e döner. **Bant yalnız ihtiyaç süresince yüksek.**
6. **Gösterim** — Sonuçlar WebSocket ile mobil/konsola (<3 KB JSON) gelir; riskli
   olaylar SQLite'a kaydedilir (`/api/events`).

---

## Proje yapısı
```
teknofest-prototip/
├── ai/                 YZ çıkarım hattı
│   ├── detector.py     YOLOv8 (gerçek) / mock dedektör
│   ├── plate_ocr.py    Çok-varyantlı plaka OCR + konsensüs
│   ├── driver_state.py MediaPipe EAR/PERCLOS yorgunluk + davranış
│   ├── speed.py        Kalibrasyonsuz bbox-tabanlı hız
│   ├── risk.py         Risk skor motoru
│   ├── tracking.py     IOU takip (track_id, bbox büyüme)
│   ├── qod_trigger.py  Akıllı QoD tetik motoru (A–E)  ← %40 kriter çekirdeği
│   ├── pipeline.py     Uçtan uca orkestrasyon
│   └── training/       Fine-tune sistemi (data.yaml, train.py)
├── backend/            FastAPI (REST+WS) + mock CAMARA + olay deposu
│   ├── main.py         API + WebSocket uçları
│   ├── qod_manager.py  Tetik motoru ↔ CAMARA QoD köprüsü
│   └── camara/         Mock QoD + Number Verification API'leri
├── frontend/           Web dashboard (güvenlik konsolu, getUserMedia)
├── mobile/             React Native / Expo uygulaması (ana ön yüz)
├── mock/               Sentetik test videosu + ground-truth
├── eval/               Normal vs Kritik doğruluk değerlendirmesi
└── tests/              pytest paketi (38 test)
```

## Yapılandırma
Tüm eşikler, sınıflar ve QoD parametreleri tek yerden: `config/settings.py` ve
`.env` (örnek: `.env.example`). Komitenin paylaşacağı **nihai etiket sınıfları ve
çıktı formatı** geldiğinde yalnızca `config/settings.py` + `ai/schema.py` güncellenir.

## Gerçek modele geçiş
`pip install ultralytics easyocr mediapipe` → `AI_MODE=auto` ile sistem otomatik
gerçek modele geçer. Mac'te (Apple Silicon) YOLO otomatik **MPS** hızlandırması kullanır.

Detaylı mimari için: **[ARCHITECTURE.md](ARCHITECTURE.md)**.
