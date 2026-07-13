# Ayrıntılı Anlatım — YZ Kolu

> **Bu belge ne?** YZ kolunun tek referans kaynağı. Üç şeyi birleştirir:
> (1) yapılan **derin kod incelemesi**, (2) repodaki **`docs/basics.md` + `docs/yz.md`**,
> (3) **şartname özeti** (TEKNOFEST 2026 · Turkcell 5G & YZ Akıllı Yol Güvenliği).
> Amaç: YZ tarafının ne olduğu, nasıl çalıştığı, ne durumda olduğu ve nereye gittiği
> tek yerde, açıklamalı olarak dursun. Değiştikçe güncellenir (bkz. `AGENTS.md` K2).

---

## 0. İçindekiler

1. Yarışma bağlamı (şartname özeti)
2. Büyük resim — sistemin 3 parçası
3. Görüntü temeli (çok kısa)
4. YZ hattı — modül modül ayrıntı
5. Çıktı sözleşmesi (FrameResult)
6. Mevcut durum & dürüst eksikler
7. Yarışma kriterlerine eşleşme
8. YZ yol haritası
9. Çalıştırma & test (Windows notlu)
10. Kısa sözlük

---

## 1. Yarışma Bağlamı (Şartname Özeti)

**Kim/ne:** TEKNOFEST 2026 kapsamında Turkcell'in düzenlediği "5G & Yapay Zeka ile
Akıllı Yol Güvenliği" yarışması.

**İstenen:** Sabit bir kameranın canlı görüntüsünü YZ ile işleyip araç, plaka, gerçek
hız, araç içi nesne ve **riskli sürücü davranışları** (telefon, sigara, yorgunluk)
tespit etmek. Sistem bir "kritik durum" algıladığında **5G QoD (Quality on Demand)
API** ile geçici olarak yüksek ağ kalitesi talep edip daha başarılı analiz yapmalı —
**ama bant sürekli yüksek tutulmamalı, yalnızca ihtiyaç anında.**

**Kullanılacak 5G API'leri:** Number Verification (SMS'siz, SIM tabanlı sessiz kimlik
doğrulama) ve Quality on Demand (ihtiyaç anında bant yükseltme). **Mobil uygulama zorunlu.**

**Puanlama (final):**
- **%40 — YZ analizi doğruluk/hassasiyeti** (araç, plaka, gerçek hız, araç içi nesne).
- **%40 — 5G QoD entegrasyonu** (yalnızca ihtiyaç varken bant yükseltme).
- **%20 — yazılım mimarisi + rapor/sunum** (modern pratikler).

**Önemli kurallar (transkriptten):** Kamera **sabit ve dışarıdan** bakar; **tüm araçlar**
tespit edilmeli (sadece TOGG değil); final değerlendirme **gizli test setiyle** (farklı
araç, açı, hava) yapılır → **genel çözüm** beklenir, tek videoya özel çözüm istenmez.
Kapalı otopark yalnızca örnek/demo ortamıdır.

**Bizim payımız (YZ kolu):** %40 YZ doğrudan bizde. Ayrıca %40'lık QoD kriterinin
**karar mantığı** (`ai/qod_trigger.py`) da bizde — yani QoD'nin "beyni" YZ kolunda,
yalnızca CAMARA'ya bağlama kısmı (`backend/qod_manager.py`) API kolunda. Kısaca puanın
büyük kısmı bizim kolumuzdan geçiyor.

---

## 2. Büyük Resim — Sistemin 3 Parçası

```
 📱/🖥️ ÖN YÜZ            🖥️ BACKEND (FastAPI)         🤖 YZ HATTI (ai/) — BİZ
 Mobil(Expo)+Web   ──kare(WS)──►  /ws/ingest      ──►  pipeline.process(frame, critical)
 getUserMedia      ◄─sonuç(JSON)─ /ws/detections  ◄──  FrameResult + TriggerContext
 (yol kenarı kamera)              mock CAMARA QoD  ◄──  TriggerContext → bant kararı
                                  SQLite olay
```

**Akış:** Ön yüz kamerayı 640px'e küçültüp JPEG olarak saniyede ~5-7 kez WebSocket
(`/ws/ingest`) ile yollar → backend kareyi **bizim** `Pipeline.process()`'e verir →
biz `FrameResult` (sonuç) + `TriggerContext` (QoD girdisi) üretiriz → QoD Manager
koşulları değerlendirip gerekirse bant yükseltir → sonuç ön yüze WebSocket ile döner
(<3 KB JSON) → riski 30+ olay SQLite'a yazılır.

**Bizim kutumuz:** Girdi = ham kare (numpy BGR dizisi). Çıktı = `FrameResult` +
`TriggerContext`. Başka bağ yok → YZ kolu bağımsız geliştirilip test edilebilir.

---

## 3. Görüntü Temeli (Çok Kısa)

Bilgisayar bir görüntüyü sayı tablosu olarak görür. Her piksel için 3 sayı (Mavi,
Yeşil, Kırmızı — **BGR**, OpenCV alışkanlığı), her biri 0-255. Görüntü = **`(yükseklik,
genişlik, 3)` boyutunda NumPy dizisi**. Örn. 640×480 = 921.600 sayı. Tüm YZ kodu bu dizi
üzerinde çalışır.

---

## 4. YZ Hattı — Modül Modül Ayrıntı

Her modülün altında: **ne yapar**, **nasıl çalışır**, ve gerekiyorsa **[inceleme notu]**
(derin kod incelemesinden dikkat edilecek nokta).

### 4.1 `ai/detector.py` — Araç + Nesne Tespiti

**Ne yapar:** Karedeki araçları ve araç içi nesneleri (telefon, insan) bulur.

**Nasıl:** **YOLOv8** ("You Only Look Once") — görüntüye bir kez bakıp tüm nesneleri
aynı anda bulan hızlı bir tespit modeli. Çıktısı her nesne için `label + bbox(x1,y1,x2,y2)
+ confidence`. İki profil var: **`yolov8n`** (nano, Normal mod — hızlı) ve **`yolov8s`**
(small, Kritik mod — daha doğru). COCO sınıfları (`car/truck/bus/motorcycle`) tek bir
**`vehicle`**'a haritalanır (`config.settings.COCO_TO_CANONICAL`).

**Mock & gerçek:** `AI_MODE=real` + ultralytics kuruluysa `YoloDetector`; değilse
`MockDetector` (piksel parlaklığına bakıp en parlak bölgeyi "araç" sayan basit kod).
Cihaz çözümü otomatik: CUDA → MPS → CPU sırasıyla (`_resolve_device`).

**[İnceleme notu]** COCO modeli `cigarette/seatbelt/headphone` sınıflarını **bilmez**;
bunlar fine-tune sonrası gelir. NVIDIA 4060'ta `_resolve_device` zaten **CUDA**'yı seçer.

### 4.2 `ai/tracking.py` — Araç Takibi

**Ne yapar:** Karelerde aynı araca **kalıcı `track_id`** verir ve bbox alan geçmişini tutar.

**Nasıl:** **IOU (Intersection over Union)** = iki dikdörtgenin örtüşme/birleşme oranı.
Örtüşme eşiğin (0.3) üstündeyse aynı araç (aynı id), değilse yeni araç. Her track
`area_history` (bbox alanı) ve `center_history` (merkez) tutar.

**Neden önemli:** Hız tahmini ve QoD'nin "yaklaşma" koşulu (`area_growth_ratio`) bu
geçmişe dayanır. Takip olmadan "araç hareket etti mi / yaklaşıyor mu" bilinemez.

### 4.3 `ai/speed.py` — Hız Tahmini (Kalibrasyonsuz)

**Ne yapar:** Radar/GPS olmadan, **piksel hareketinden** yaklaşık hız üretir.

**Nasıl:** Araç yaklaştıkça bbox büyür. İki bileşenin büyüğü alınır:
```
da = |alan_şimdi - alan_önce| / toplam_alan        # yaklaşma (alan büyümesi)
dc = |merkez_şimdi - merkez_önce| / köşegen         # yanal/boyuna kayma
movement = max(da^0.65, dc)                          # baş-on gelende alan, yandan gelende merkez
speed_kmh = K * movement * (fps/30)                  # K = speed_calibration_k = 900 (deneysel)
```
`max(...)` kullanımı, kameraya **dik gelen** araçta (merkez oynamaz ama bbox büyür)
"0 km/h" hatasını çözer.

**[İnceleme notu]** `K=900` **keyfi**; gerçek km/h anlamlı değil. Saha kalibrasyonu
(bilinen mesafe/araç boyu) ile netleşir. Demoda **HIZ_AŞIMI ihlali eşik-tabanlı**
tetiklendiği için kalibrasyon hatası ihlal kararını bozmaz — ama "gerçek hız doğruluğu"
(şartname kriteri) için kalibrasyon şart.

### 4.4 `ai/plate_ocr.py` — Plaka Okuma

**Ne yapar:** Araç plakasını metne çevirir (**yalnızca Kritik modda**).

**Nasıl (2 aşama):**
1. **Plaka bölgesini bul:** `pipeline.py` araç bbox'ının alt orta kısmını keser
   (x: %20–%80, y: %60–%100 — plaka genelde altta).
2. **OCR:** crop üç varyanta çevrilir (orijinal, **CLAHE** kontrast, **ters**), her birine
   EasyOCR koşulur, en yüksek güvenli sonuç seçilir; sonuç **Laplacian keskinliği** ile
   ağırlıklanır (bulanık kare daha az etkiler).

**Konsensüs + format:** Son 8 okuma karakter pozisyonu bazında çoğunluk oyuna girer
(tek karedeki hatayı dengeler). Türk plaka regex'i (`^(0[1-9]|[1-7][0-9]|8[01])[A-Z]{1,3}[0-9]{2,4}$`)
ve **0.70 güven eşiği** geçmeyen plaka **gösterilmez** (`—`).

**[İnceleme notu]** Plaka **sadece Kritik modda** okunur (QoD tetiklenmeden okunmaz).
Mock modda PlateReader plaka **üretmez** → mock'ta `plate.text = None`. Eski projedeki
"34 TC 8532" tam-doğruluk birikimi (adaptive Y-crop, I→T düzeltmesi, çok-kareli konsensüs)
buraya taşınabilir.

### 4.5 `ai/driver_state.py` — Sürücü Durumu

**Ne yapar:** Tehlikeli sürücü davranışlarını çıkarır.

**Nasıl:**
- **Yorgunluk:** MediaPipe Face Mesh ile gözün 6 noktasından **EAR (Eye Aspect Ratio)**:
  `EAR = (|P2-P6| + |P3-P5|) / (2·|P1-P4|)`. Göz açıkken ~0.30, kapanınca <0.21. Son 30
  karede kapalılık oranı **PERCLOS** > %40 → yorgun. (Yalnızca Kritik profilde, güvenilirlik için.)
- **Telefon/sigara:** Tespit edilen nesne, aracın **sol-üst kabin ROI**'siyle (%55×%75)
  örtüşüyorsa sürücü davranışı sayılır.

**[İnceleme notu]** `seatbelt`/`cigarette`/`headphone` COCO'da olmadığı için fine-tune'a
kadar **inert** (kemer kodda kasıtlı `False`). Telefon (COCO `cell phone`) gerçek modelde çalışır.

### 4.6 `ai/risk.py` — Risk Skoru

**Ne yapar:** Tüm sürücü bayraklarını tek **0-100** skora indirger.

| Etken | Puan | | Etken | Puan |
|---|---|---|---|---|
| Telefon | +40 | | Hız aşımı (>50) | +15 |
| Yorgunluk | +30 | | Kemer yok | +15 |
| Sigara | +20 | | Zigzag | +10 |
| | | | Kulaklık | +5 |

Seviyeler: 0-29 **LOW**, 30-59 **MEDIUM**, 60-84 **HIGH**, 85-100 **CRITICAL**.
Ağırlıklar `config.settings.RISK_WEIGHTS`'te (tek noktadan ayarlanır).

### 4.7 `ai/qod_trigger.py` — QoD Tetik Motoru (%40 Kriterin Beyni)

**Ne yapar:** "Ne zaman bant yükselsin?" kararını verir. **Projenin en kritik bileşeni.**

**Nasıl:** 500 ms'de bir 5 koşul:
| Koşul | Anlamı |
|---|---|
| **A** | bbox hızla büyüyor (araç yaklaşıyor) |
| **B** | tespit güveni düşük (model emin değil) |
| **C** | plaka ROI var ama OCR güveni düşük |
| **D** | araç ROI çizgisini geçti (okuma menzilinde) |
| **E** | araç içi nesne sınır olasılıkta (0.40–0.60) |

Koşullardan biri **iki ardışık döngüde** pozitifse → **Kritik moda geç** (CAMARA QoD'ye
"bant artır", ağır model + plaka OCR devreye). **Bırakma:** güven>0.85 / 5 sn doldu /
araç ROI dışına çıktı → Normal'e dön.

**Önemli:** Bu modül **saf mantıktır** (ağ çağrısı yok) → kolay ve eksiksiz test edilir
(`tests/test_qod_trigger.py`). Bant **sürekli yüksek tutulmaz**; `bandwidth_efficiency`
metriği "sürekli yükseğe göre ne kadar tasarruf" ölçer — bu, şartname %40'ının **sayısal kanıtı**.

### 4.8 `ai/pipeline.py` — Orkestratör

**Ne yapar:** Bir kare için 6 bloğu sırayla koşturup sonucu birleştirir.
```
Kare → [A] tespit → [B] takip → [C] hız → [D] plaka(kritik) → [E] sürücü → [F] risk
     → FrameResult + TriggerContext
```
Birincil araç = en büyük bbox'lı araç. Renk basit baskın-kanal tahmini ile.

**[İnceleme notu]** Şu an **birincil tek araç** işleniyor; şartname "tüm araçlar" istiyor
→ çoklu-araç genişletme yol haritasında (Faz 9).

### 4.9 `ai/schema.py` — Veri Sözleşmesi

Backend ve mobil ile paylaşılan Pydantic tipleri: `BBox, Detection, PlateResult,
DriverState, Vehicle, RiskAssessment, QoDStatus, FrameResult, EventRecord`. Bu dosya
**kontrattır** — alan değişirse backend kolu (arkadaş) uyarılır (bkz. AGENTS.md K5).

### 4.10 `ai/training/` — Fine-Tune Sistemi

COCO modeli sigara/kemer/kulaklık bilmez. Komite verisi gelince: `prepare_dataset.py`
(videodan kare çıkar + YOLO iskeleti) → `data.yaml` (7 sınıf) → `train.py` (augmentation:
mozaik/mixup/renk jitter; INT8 export). Çıktı `best.pt` → `config`'te `yolo_model_critical`.
Strateji: **COCO → açık kaynak (BDD100K, CCPD) → saha** üç aşamalı transfer.

---

## 5. Çıktı Sözleşmesi (FrameResult < 3 KB)

Her kare için ön yüze giden JSON'un özü:
```jsonc
{
  "mode": "NORMAL|CRITICAL",
  "detections": [{ "label": "vehicle", "confidence": 0.9, "bbox": {...} }],
  "vehicle": { "present": true, "plate": {"text": "34 TC 8532"}, "speed_kmh": 22, "vtype": "car", "color": "beyaz" },
  "driver": { "phone_use": true, "fatigue": false, "ear": 0.28, "perclos": 0.1 },
  "risk": { "score": 55, "level": "MEDIUM", "factors": ["telefon_kullanimi"] },
  "qod": { "mode": "CRITICAL", "bandwidth_mbps": 20, "last_trigger_reason": "A:yaklasma" },
  "latency_ms": 18, "fps": 50
}
```

---

## 6. Mevcut Durum & Dürüst Eksikler

**Çalışan:** Uçtan uca YZ hattı (mock + COCO-pretrained), QoD tetik motoru, risk skoru,
şema kontratı, test paketi, fine-tune iskeleti. Mimari temiz ve katmanlı (%20 kriteri için iyi).

**Eksikler / riskler (kod incelemesinden):**
1. **Platform:** Repo macOS varsayıyor (`run_dev.sh`, MPS, iPhone). Bizim kurulum
   **Windows + NVIDIA 4060** → çalıştırma uyarlaması gerekli (CUDA tarafı kodda hazır).
2. **Gerçek model yok:** COCO/mock. Sigara/kemer/kulaklık fine-tune'a kadar üretilemez.
3. **Olası kırık test:** `test_pipeline_reads_plate_in_critical` mock'ta düşebilir (mock plaka üretmiyor) — `make test` ile teyit edilmeli.
4. **Tek-araç:** Pipeline birincil aracı işliyor; "tüm araçlar" için genişletme gerek.
5. **Hız kalibrasyonsuz:** `K=900` deneysel; gerçek hız için saha ölçümü.
6. **Küçük:** plaka yalnız Kritik modda okunur (tasarım gereği — QoD'siz okunmaz).

---

## 7. Yarışma Kriterlerine Eşleşme

| Kriter | Ağırlık | Bizdeki karşılığı | Durum |
|---|---|---|---|
| YZ doğruluk/hassasiyet | %40 | `pipeline` + `detector/plate_ocr/driver_state/speed/risk` | Mimari hazır; **gerçek model + ölçüm** gerekli |
| QoD entegrasyonu (ihtiyaç-bazlı bant) | %40 | `qod_trigger` (A–E) + `bandwidth_efficiency`; bağlama backend'de | **Karar mantığı güçlü** ve test edilmiş |
| Mimari + rapor | %20 | katmanlı, tip-güvenli, testli, config-tek-nokta | İyi durumda |

**Stratejik vurgu:** Güçlü olduğumuz yer **QoD tetik mantığı** (saf, test edilmiş,
ölçülebilir). Yatırım yapılacak yer **YZ doğruluğu** (gerçek model + kalibrasyon + fine-tune).

---

## 8. YZ Yol Haritası

1. **Windows/CUDA çalıştırma** doğrula (`make test` durumu dahil).
2. **Gerçek YOLOv8** (4060) → 3 test videosunda tespit + FPS ölçümü.
3. **Plaka OCR gerçek** (EasyOCR + GPU); eski projedeki tam-doğruluk birikimini taşı.
4. **Sürücü davranışı:** telefon gerçek test; MediaPipe yorgunluk denemesi.
5. **Hız kalibrasyonu** (`speed_calibration_k`).
6. **QoD doğrulama:** `make eval` ile Normal vs Kritik doğruluk + bant verimliliği raporu.
7. **Fine-tune:** komite verisiyle sigara/kemer/kulaklık.
8. **Çoklu-araç** genişletme.

Her adımda: açıklamalı kod + `make test` + ölçüm + `PROGRESS.md` güncellemesi (AGENTS.md K1–K2).

---

## 9. Çalıştırma & Test (Windows Notlu)

```bash
# Backend (mock mod — kütüphane gerekmez, uçtan uca çalışır):
#   macOS/Linux:  ./run_dev.sh
#   Windows:      python -m venv .venv ; .venv\Scripts\activate ;
#                 pip install -r requirements.txt ;
#                 set AI_MODE=auto ; python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
# Sağlık kontrolü: http://localhost:8000/api/health

# Testler (mock, deterministik):
make test          # Windows: .venv\Scripts\python -m pytest -q

# Gerçek model (NVIDIA 4060):
pip install ultralytics easyocr mediapipe torch   # CUDA 11.8 derlemesi
set AI_MODE=real

# Doğruluk değerlendirmesi (Normal vs Kritik + bant verimliliği):
make eval
```

---

## 10. Kısa Sözlük

- **YOLOv8:** gerçek zamanlı nesne tespit modeli (araç/telefon vb.).
- **bbox:** tespit edilen nesnenin etrafındaki dikdörtgen (x1,y1,x2,y2).
- **IOU:** iki bbox'ın örtüşme/birleşme oranı (takip eşleştirmesi).
- **OCR:** görüntüdeki yazıyı metne çevirme (plaka).
- **EAR / PERCLOS:** göz açıklık oranı / kapalılık yüzdesi (yorgunluk).
- **QoD:** Quality on Demand — 5G'de ihtiyaç anında bant yükseltme.
- **CAMARA:** 5G şebeke API'lerini standartlaştıran açık kaynak proje (QoD, Number Verification).
- **Mock:** gerçek yerine taklit/simülasyon (model veya 5G yokken sistemi ayakta tutar).
- **Profile (Normal/Kritik):** Normal=hafif model+düşük bant; Kritik=ağır model+yüksek bant+OCR.
- **FrameResult / TriggerContext:** YZ'nin ürettiği sonuç JSON'u / QoD karar girdisi.
