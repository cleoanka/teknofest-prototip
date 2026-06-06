# AGENTS.md — YZ Kolu Çalışma Kuralları

> Bu repo `cleoanka/teknofest-prototip` temel alınarak yürütülüyor.
> **Bizim kolumuz: Yapay Zeka (`ai/`).** Diğer kollar (backend, mobil, entegrasyon,
> rapor) takım arkadaşlarımızda. Bu dosya **YZ kolunun** nasıl çalıştığını ve diğer
> kollarla sözleşmesini tanımlar. **Her adımda güncellenir** (bkz. Kural K2).

---

## 1. Proje (tek cümle)

TEKNOFEST 2026 · Turkcell **5G & Yapay Zeka ile Akıllı Yol Güvenliği**: sabit bir
kameradan gelen canlı görüntüyü YZ ile işleyip araç / plaka / hız / sürücü davranışı
tespit eden, **tehlike anında 5G QoD ile bandı yükselten** uçtan uca sistem. Çözüm
tek ortama/araca özel değil; her yerde, her araçta çalışacak genel bir sistem hedefler
(demo/test ortamı: kapalı otopark).

---

## 2. Kapsam — Bizim Sorumluluğumuz

| Kol | Sahip | Dosyalar |
|---|---|---|
| **YZ (BİZ)** | Bizim takım | `ai/` · `config/settings.py` (YZ eşikleri) · `eval/` |
| API / Backend | Arkadaş | `backend/` |
| Mobil | Arkadaş | `mobile/` |
| Entegrasyon | Arkadaş | `frontend/` · `tests/` |
| Rapor / Sunum | Arkadaş | `docs/` · sunumlar |

**Biz `ai/` içindeki her şeyden sorumluyuz:** araç tespiti, takip, plaka OCR, hız
tahmini, sürücü durumu, risk skoru, **QoD tetik mantığı** (`qod_trigger.py`), çıkarım
hattı (`pipeline.py`), veri şeması (`schema.py`) ve model eğitimi (`training/`).

> Not: QoD'nin **karar mantığı** (ne zaman bant yükselsin) bizde (`ai/qod_trigger.py`);
> bu kararı CAMARA'ya **bağlama** kısmı (`backend/qod_manager.py`) API kolunda. Yani
> yarışmanın **%40 QoD kriterinin beyni de bizde**.

---

## 3. Değişmez Çalışma Kuralları

### K1 — Her zaman açıklamalı kod
- Her dosyanın başında **docstring**: ne yapar, neden var, hangi şartname maddesine hizmet eder.
- Bölüm başlıkları yorumla: `# --- Bölüm Adı ---`.
- **Türkçe** yorum satırları.
- Sadece "ne" değil **"neden"i** de yaz — özellikle eşik/sabit seçimlerinde (ör. `EAR_THRESHOLD = 0.21  # göz kapalı sayılma sınırı, DROZY referansı`).
- Karmaşık formülün yanına 1 satır açıklama (ör. EAR, IOU, hız formülü).

### K2 — Her adımda dokümante et
- Her teknik değişiklikten sonra **`PROGRESS.md`**'ye satır ekle: *ne yapıldı, neden, ölçülen sonuç*.
- Yeni teknik karar → `PROGRESS.md` **Karar Günlüğü**ne.
- Bu **`AGENTS.md`**'yi güncel tut (öncelik sırası, kurallar değişirse).
- Sistemin nasıl çalıştığına dair derin değişiklik → **`ayrıntılıanlatım.md`**'yi güncelle.
- **Ölçüm olmadan "tamam" denmez** (FPS, doğruluk, tespit oranı vb.).

### K3 — Config tabanlı
- Tüm eşik / sabit / model yolu **`config/settings.py`**'de. **Hardcode yok.**
- Değişiklik tek noktadan yapılır, her yere etki eder.

### K4 — Mock-first korunur
- **`AI_MODE=auto`** graceful degradation **bozulmaz**. Kütüphane (ultralytics/easyocr/
  mediapipe) yoksa sistem otomatik **mock**'a düşüp uçtan uca çalışmaya devam etmeli,
  testler yeşil kalmalı. Yeni modül eklerken aynı "kütüphane yoksa mock'a düş" desenini uygula.

### K5 — Sözleşmeyi koru (YZ ↔ Backend)
- **`ai/schema.py`** (FrameResult, Detection, Vehicle, ...) backend ile **kontrattır**.
  Alan eklersen/değiştirirsen **API kolunu (arkadaş) uyar**; tek taraflı kırma.
- **`Pipeline.process(frame, critical) -> (FrameResult, TriggerContext)`** imzası sabittir.
- `FrameResult` JSON'u **< 3 KB** kalmalı (ÖTR hedefi).

### K6 — Test ve küçük adım
- **Tek seferde tek modül** değiştir, test et, sonra sonrakine geç.
- Her değişiklikten sonra `make test` (mock modda). Saf-mantık testleri
  (`test_risk`, `test_speed`, `test_qod_trigger`) **her zaman** geçmeli.
- Gerçek modelle çalışırken 3 test videosunu da koştur, sonuçları `experiments/` veya PROGRESS'e yaz.

### K7 — Git ile kaydet, GitHub'a gönder
- **Her tamamlanan adım kendi commit'i olur.** "Adım" = anlamlı bir bütün (bir modül/değişiklik
  + testi + dokümanı). Yarım iş commit'lenmez; commit'lenen iş **mock testleri yeşilken** alınır.
- **Sıra:** kod/doküman değişikliği → `make test` yeşil → `PROGRESS.md` güncel → `git add` → `git commit`
  → `git push`. Yani PROGRESS/AGENTS güncellemesi **aynı commit'in içinde** gider.
- **Commit mesajı (Türkçe, anlamlı):** `<alan>: <ne yapıldı> (neden)`. Alan biri:
  `ai`, `config`, `eval`, `docs`, `test`, `chore`.
  Örn: `ai: plaka OCR gerçek EasyOCR'a alındı (34 TC 8532 doğruluğu için)`.
- **Atomik tut:** bir commit tek konuyu çözer. Karışık değişiklikleri tek commit'e tıkma.
- **`.gitignore`'a uy:** model ağırlıkları (`*.pt`), videolar, `.venv/`, `.env`, büyük çıktılar
  commit'lenmez. Gizli anahtar/token **asla** commit'lenmez (`.env.example` şablon kalır).
- **Push düzeni:** çalışılan dal `main` (veya kararlaştırılan dal). Push'tan önce `git pull --rebase`
  ile çakışmayı önle; çakışma varsa çöz, sonra push et.
- **Geri alınabilirlik:** her commit tek başına derlenip mock testleri geçmeli — böylece gerekirse
  tek adım geri sarılabilir.

---

## 4. Mimari Sözleşme (YZ ↔ Backend)

```
[Ham kare numpy BGR]
        │
        ▼
  ai/pipeline.py  Pipeline.process(frame, critical)
        │
        ├─► FrameResult      → backend → WS → mobil/web  (<3 KB JSON)
        └─► TriggerContext   → backend/qod_manager.py → CAMARA QoD
```

Backend bize **ham kare** verir, bizden **`FrameResult` + `TriggerContext`** alır.
Başka hiçbir bağ yok — bu yüzden YZ kolu bağımsız geliştirilebilir/test edilebilir.

---

## 5. YZ Modülleri (kol içi sahiplik)

| Dosya | Görev |
|---|---|
| `ai/detector.py` | Araç + araç içi nesne tespiti (YOLOv8 gerçek / MockDetector) |
| `ai/tracking.py` | IOU takip → `track_id`, bbox alan geçmişi (hız + QoD koşul A) |
| `ai/speed.py` | Kalibrasyonsuz bbox-alan tabanlı hız tahmini |
| `ai/plate_ocr.py` | Çok-varyantlı plaka OCR + keskinlik/konsensüs (yalnız kritik) |
| `ai/driver_state.py` | EAR/PERCLOS yorgunluk + telefon/sigara (ROI çakışma) + MediaPipe el füzyonu + sürücü kimliği |
| `ai/mp_cabin.py` | MediaPipe Hands kabin analizi (el→kulak/ağız → telefon/sigara füzyon sinyali) |
| `ai/mp_seatbelt.py` | MediaPipe Pose + çapraz şerit heuristiği (emniyet kemeri tespiti → `no_seatbelt`) |
| `ai/risk.py` | Ağırlıklı 0-100 risk skoru |
| `ai/qod_trigger.py` | **QoD tetik motoru (A–E, 2 ardışık)** — %40 kriter beyni |
| `ai/pipeline.py` | 6 bloğu birleştiren orkestratör |
| `ai/schema.py` | Veri tipleri / backend kontratı |
| `ai/training/` | COCO → saha fine-tune sistemi |
| `config/settings.py` | Tüm eşik/sabit/model yolu (tek nokta) |
| `eval/evaluate.py` | Normal vs Kritik doğruluk + bant verimliliği ölçümü |

---

## 6. Definition of Done (YZ tarafı)

Bir iş "bitti" sayılır eğer:
- Kod **açıklamalı** (K1) ve **config tabanlı** (K3).
- `make test` yeşil; ilgili saf-mantık testi varsa eklendi/geçiyor.
- **Ölçüm** alındı (gerçek modelde: 3 videoda FPS + tespit oranı; mock'ta: test).
- `PROGRESS.md` güncellendi (ne/neden/sonuç) ve gerekiyorsa Karar Günlüğü eklendi.
- Mock fallback hâlâ çalışıyor (K4), schema sözleşmesi korunuyor (K5).
- **Değişiklik git'e commit'lendi ve GitHub'a push'landı** (K7) — doküman güncellemesi aynı commit'te.

---

## 7. Öncelik Sırası (YZ Yol Haritası)

1. **Windows + CUDA çalıştırma doğrulaması** — backend'i Windows'ta ayağa kaldır, `make test` durumunu gör (repo macOS varsayıyor).
2. **Gerçek YOLOv8 devreye** — `AI_MODE=real`, NVIDIA 4060/CUDA; 3 test videosunda araç tespiti + FPS ölçümü.
3. **Plaka OCR gerçek** — EasyOCR'ı GPU ile; "34 TC 8532" doğruluğu (eski projedeki birikimi taşı).
4. **Sürücü davranışı** — telefon (COCO class) gerçek test; MediaPipe yorgunluk denemesi.
5. **Hız kalibrasyonu** — `speed_calibration_k` saha/referans ölçümüyle.
6. **QoD doğrulama** — `eval/evaluate.py` ile Normal vs Kritik doğruluk farkı + `bandwidth_efficiency` raporu.
7. **Fine-tune** — komite verisi gelince `ai/training/` ile (sigara/kemer/kulaklık sınıfları).
8. **Çoklu-araç** — pipeline'ı "tüm araçlar"a genişlet (şu an birincil araç).

---

## 8. Yapılmaması Gerekenler

- **Aynı anda birden çok modül** değiştirme (K6).
- **GPU thread çakışması** yaratma (aynı anda 2 thread'den YOLO koşturma).
- `schema.py`'yi **backend'e haber vermeden** kırma (K5).
- **Mock fallback'i bozma** (K4).
- **Ölçümsüz** "tamam" deme (K2).
- `speed_kmh`'i **kalibrasyonsuz** "gerçek hız" diye sunma (yalnız ihlal eşiği için kullan).
- Tek bir test videosuna **özel** çözüm yazma — gizli test seti farklı araç/açı/hava (şartname). Genel kal.
- **Yarım/kırık iş commit'leme** (K7): mock testleri kırmızıysa push etme.
- **Sır/anahtar, model ağırlığı, video veya `.venv` commit'leme** — `.gitignore` dışına taşma.
- **Devasa "her şeyi tek seferde" commit** atma — adım adım, atomik commit'le.
