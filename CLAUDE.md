# CLAUDE.md

Bu dosya, bu depoda çalışan Claude Code (ve diğer YZ ajanları) için rehberdir.
Amaç: hızlı yönlenmek, doğru komutları çalıştırmak ve projenin **değişmez
kurallarını** bozmadan katkı yapmak.

> Dil: Bu proje Türkçe yürütülür. **Kod yorumları, commit mesajları ve dokümanlar
> Türkçedir** (bkz. Kural K1). Kod tanımlayıcıları (değişken/fonksiyon adları) İngilizce.

---

## Proje (tek cümle)

TEKNOFEST 2026 · Turkcell **5G & Yapay Zeka ile Akıllı Yol Güvenliği**: sabit
kameradan gelen canlı görüntüyü YOLO + OCR + MediaPipe ile işleyip araç / plaka /
hız / sürücü davranışı tespit eden, **tehlike anında 5G CAMARA QoD ile bandı
yükseltip tehlike geçince düşüren** uçtan uca çalışan prototip.

Üç bağımsız parça: **Mobil/Web ön yüz ↔ Backend (FastAPI) ↔ YZ çıkarım hattı (`ai/`)**.

Puanlama: YZ doğruluğu %40 · 5G QoD ihtiyaç-bazlı bant %40 · Mimari & pratikler %20.

---

## Sık Kullanılan Komutlar

```bash
# Kurulum (sanal ortam + paketler)
make install

# Backend + Web dashboard (geliştirme)
make run                       # AI_MODE=auto, http://localhost:8000
./run_dev.sh start             # arka planda (macOS/Linux) · stop|restart|status|logs
.\run_dev.ps1 start            # Windows PowerShell

# Testler — DAİMA mock modda yeşil kalmalı (model gerektirmez)
make test                      # = AI_MODE=mock pytest
AI_MODE=mock python -m pytest tests/test_qod_trigger.py   # tek dosya
AI_MODE=mock python -m pytest -k "risk or speed"          # desenle filtre

# Değerlendirme / doğruluk raporu
make eval                      # sentetik veri + Normal vs Kritik + bant verimliliği
make mock                      # sentetik test videosu üret

# Gerçek model duman testi (ultralytics vb. kurulu olmalı)
AI_MODE=real python -m eval.real_smoke
AI_MODE=real python -m tools.smoke_real_model

# Video test aracı (kamera olmadan)
python tools/test_video.py video.mp4 --scale 0.5 --every 2 --json-out r.json

# Veri / eğitim araçları
python -m ai.training.fetch_data list
python -m ai.training.prepare_dataset verify --data ai/training/data.yaml
python -m ai.training.train --tier critical --curriculum --dry-run

# Temizlik
make clean                     # venv + cache + db + mock çıktıları
```

Test yapılandırması `pytest.ini`'de (`asyncio_mode=auto`, `testpaths=tests`).
Mobil için: `cd mobile && npm install && npx expo start`.

---

## Mimari & Sözleşme

```
[Ham kare numpy BGR]
        │  backend ham kare verir
        ▼
  ai/pipeline.py   Pipeline.process(frame, critical) -> (FrameResult, TriggerContext)
        ├─► FrameResult     → backend → WebSocket → mobil/web   (< 3 KB JSON)
        └─► TriggerContext  → backend/qod_manager.py → CAMARA QoD (bant aç/kapa)
```

YZ ile backend arasındaki **tek bağ budur** — bu yüzden `ai/` bağımsız test edilir.

İki kademe: Normal modda `yolov8n` (hız), kritik modda daha büyük model + OCR +
MediaPipe (doğruluk). QoD kararı (`ai/qod_trigger.py`) 500ms döngüde A–E
koşullarından 2 ardışık pozitif arar; bağlama backend'tedir.

---

## Değişmez Kurallar (özet — tam metin `ai/AGENTS.md`)

- **K1 — Açıklamalı kod:** Her dosyada Türkçe docstring (ne/neden/hangi şartname
  maddesi). Eşik/sabit seçiminin **"neden"ini** yaz. Karmaşık formüle 1 satır not.
- **K2 — Her adımda dokümante et:** Teknik değişiklikten sonra `ai/PROGRESS.md`'ye
  satır ekle (ne/neden/ölçülen sonuç). **Ölçüm olmadan "tamam" denmez** (FPS,
  doğruluk, tespit oranı). Derin değişiklik → `ayrıntılıanlatım.md`.
- **K3 — Config-first:** Tüm eşik/sabit/model yolu `config/settings.py` + `.env`.
  **Hardcode yok.** Değişiklik tek noktadan.
- **K4 — Mock-first:** `AI_MODE=auto` graceful degradation bozulmaz. Kütüphane
  (ultralytics/easyocr/mediapipe) yoksa modül mock'a düşer, sistem çökmez, testler
  yeşil kalır. Yeni modülde aynı deseni uygula.
- **K5 — Sözleşmeyi koru:** `ai/schema.py` (FrameResult, Detection, Vehicle, ...)
  backend kontratıdır. Alan ekler/değiştirirsen API kolunu **uyar**, tek taraflı
  kırma. `Pipeline.process` imzası sabit. `FrameResult` JSON'u **< 3 KB**.
- **K6 — Tek modül, küçük adım:** Tek seferde tek modül değiştir → test et → sonraki.
  Saf-mantık testleri (`test_risk`, `test_speed`, `test_qod_trigger`) her zaman geçmeli.
- **K7 — Atomik commit:** Sıra: kod/doküman → `make test` yeşil → `PROGRESS.md`
  güncel → `git add` → `git commit` → `git push`. Doküman güncellemesi **aynı
  commit'te**. Mesaj: `<alan>: <ne yapıldı> (neden)` — alan: `ai|config|eval|docs|test|chore`.

### Yapılmaması Gerekenler

- Aynı anda birden çok modül değiştirme (K6) · Aynı anda 2 thread'den YOLO koşturma.
- `schema.py`'yi backend'e haber vermeden kırma (K5) · Mock fallback'i bozma (K4).
- Ölçümsüz "tamam" deme · `speed_kmh`'i kalibrasyonsuz "gerçek hız" diye sunma.
- Tek bir test videosuna özel çözüm yazma — gizli test seti farklı (genel kal).
- Sır/token, model ağırlığı (`*.pt`), video veya `.venv`/`.env` commit'leme (`.gitignore`).

---

## Depo Haritası

```
ai/                  🤖 YZ çıkarım hattı (BİZİM kol — her şeyden sorumluyuz)
  pipeline.py            Orkestratör · Pipeline.process(frame, critical)
  detector.py            YOLO gerçek / MockDetector
  tracking.py            IOU takip → track_id, bbox alan geçmişi
  speed.py               Bbox/homografi/PnP tabanlı hız (calibration.py, homography.py, plate_pnp.py, vanishing_point.py)
  lp_detector.py         Plaka tespiti (YOLO11n oto-indirme + CV fallback)
  plate_crop.py          Plaka crop + deskew + looks_like_plate geçidi
  plate_tracker.py       Araç-id'ye bağlı plaka kararlılığı
  plate_ocr.py           Çok-varyant OCR + konsensüs (yalnız kritik)
  driver_state.py        MediaPipe EAR/PERCLOS + sürücü/yolcu ROI ayrımı
  risk.py                Ağırlıklı 0–100 risk skoru
  qod_trigger.py         ← %40 kriter çekirdeği: A–E koşul motoru
  schema.py              ← YZ ↔ Backend kontratı (kırma!)
  training/              COCO → saha fine-tune (train.py, prepare_dataset.py, fetch_data.py)
  AGENTS.md PROGRESS.md plan.md   Kol kuralları / ilerleme günlüğü / strateji

backend/             🖥️ FastAPI (arkadaşın kolu — REST + WebSocket v1.5, auth, metrics, qod_manager, db, camara/)
frontend/            🌐 Web güvenlik konsolu (index.html, app.js)
mobile/              📱 React Native / Expo (App.tsx, src/screens, src/api)
config/settings.py   ⚙️  Tüm parametreler tek yerden (sınıf taksonomisi dahil)
eval/                📊 evaluate.py (Normal vs Kritik + bant), real_smoke.py
tools/               🔧 test_video.py, camera_client.py, smoke_real_model.py
tests/               ✅ 34 dosya pytest (mock modda çalışır)
mock/                🎭 Sentetik test verisi
docs/                📚 Kol rehberleri (yz, api, mobil, entegrasyon, rapor, basics)
```

---

## Yapılandırma (`.env`)

`cp .env.example .env`. Sık kullanılanlar:

| Parametre | Varsayılan | Açıklama |
|-----------|-----------|---------|
| `AI_MODE` | `auto` | `real` / `mock` / `auto` (kütüphane varsa gerçek) |
| `YOLO_DEVICE` | `auto` | `auto` / `cpu` / `mps` / `cuda` |
| `CAMARA_MODE` | `mock` | `mock`→`real` için sadece 4 CAMARA değişkenini doldur, kod değişmez |
| `REQUIRE_AUTH` | `false` | `true` → tüm `/api/*` JWT RS256 Bearer zorunlu |
| `RATE_LIMIT` | `100` | req/dakika/IP |
| `QOD_EVAL_PERIOD_MS` | `500` | QoD değerlendirme aralığı |

---

## Definition of Done (YZ tarafı)

- Kod açıklamalı (K1) ve config tabanlı (K3).
- `make test` yeşil; ilgili saf-mantık testi eklendi/geçiyor.
- Ölçüm alındı (gerçek modelde 3 videoda FPS + tespit; mock'ta test).
- `ai/PROGRESS.md` güncellendi; gerekirse Karar Günlüğü eklendi.
- Mock fallback çalışıyor (K4), schema sözleşmesi korunuyor (K5).
- Değişiklik commit'lendi ve push'landı (K7) — doküman aynı commit'te.

---

## Daha Fazlası

- Mimari detay: `ARCHITECTURE.md` · Sistemin derin anlatımı: `ayrıntılıanlatım.md`
- Kol rehberleri: `docs/` · Genel giriş: `docs/basics.md`
- YZ kuralları (tam): `ai/AGENTS.md` · İlerleme/karar günlüğü: `ai/PROGRESS.md`
- Backend/API referansı: `backend/README.md` · Swagger: `http://localhost:8000/docs`
</content>
</invoke>
