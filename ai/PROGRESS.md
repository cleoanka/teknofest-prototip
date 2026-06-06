# PROGRESS.md — YZ Kolu İlerleme Günlüğü

> Kapsam: **Yapay Zeka kolu (`ai/`)**. Her teknik adımdan sonra buraya satır eklenir
> (ne yapıldı / neden / ölçülen sonuç). Kurallar için bkz. `AGENTS.md`.

## Proje
TEKNOFEST 2026 · 5G & YZ ile Akıllı Yol Güvenliği. Temel repo: `cleoanka/teknofest-prototip`.

---

## 1. Mevcut Durum (son güncelleme: 2026-06-06)

**Genel:**
- Prototip repo **temel alındı**; uzak `cleoanka/teknofest-prototip` ile senkron (K7 akışı).
- YZ hattı **uçtan uca çalışıyor**: mock (73 test yeşil) **ve** gerçek GPU (CUDA torch + YOLOv8) doğrulandı.
- Eğitim/veri hattı **kodlandı ve test edildi** (aşağıdaki modüller).

**Hazır olan YZ modülleri:**
- `detector` (YOLOv8 gerçek/mock), `tracking` (IOU), `speed` (bbox-alan), `plate_ocr`
  (çok-varyant + konsensüs), `driver_state` (EAR/PERCLOS + ROI), `risk` (ağırlıklı),
  `qod_trigger` (A–E motoru), `pipeline` (orkestratör), `schema` (kontrat).
- **Eğitim/veri araçları (6 Haz):** `training/prepare_dataset` (COCO→YOLO + audit + verify),
  `training/train` (müfredat + iki kademe + export + dry-run), `training/fetch_data` (+ `sources.json`
  manifest), `eval/real_smoke` (gerçek-mod duman). Detay: Faz Durumu ve §5.

**Henüz YOK:**
- Eğitilmiş özel model (sadece COCO-pretrained / mock).
- Gerçek CAMARA 5G (mock).
- Saha hız kalibrasyonu.
- ~~Windows/CUDA üzerinde doğrulanmış çalıştırma~~ → **YAPILDI** (2026-06-06, bkz. Faz 2/3).

---

## 2. Faz Durumu

- **Faz 0 — Prototip temel alındı** ✓ (2026-06-05)
- **Faz 1 — Mimari + derin kod incelemesi** ✓ (2026-06-05)
- **Faz 2 — Windows/CUDA çalıştırma doğrulaması** ✓ (2026-06-06) — venv'e torch 2.6.0+cu124 + ultralytics
  8.4.60 kuruldu; `torch.cuda.is_available()=True`, **RTX 4070 Laptop (8GB)** görülüyor; mock paketi 73 yeşil.
- **Faz 3 — Gerçek YOLOv8 + FPS ölçümü** ✓ MİNİ (2026-06-06) — coco8 ile **gerçek GPU eğitimi `train.py`
  üzerinden uçtan uca koştu** (3 epoch, best.pt üretildi, test→val geri-düşüşü çalıştı). **yolov8n: 72.7 FPS**
  (RTX 4070, imgsz 640) → plan hedefi "Normal mod >25 FPS" ✓. 3 saha/test videosuyla ölçüm → BEKLEYEN (veri gelince).
- **Faz 4 — Plaka OCR gerçek (EasyOCR + GPU)** → BEKLEYEN
- **Faz 5 — Sürücü davranışı (telefon gerçek + yorgunluk denemesi)** → BEKLEYEN
- **Faz 6 — Hız kalibrasyonu** → BEKLEYEN
- **Faz 7 — QoD doğrulama (eval: Normal vs Kritik + bant verimliliği)** → BEKLEYEN
- **Faz 8 — Fine-tune (komite verisi gelince)** → BEKLEYEN
  - *(2026-06-05)* Eğitim **planı dokümante edildi** → `ai/plan.md`: sıfır etiketten açık kaynak veriyle
    geniş eğitim stratejisi (ne / nasıl / hangi kaynaklardan) + donanım yol haritası. Henüz eğitim koşulmadı.
  - *(2026-06-05)* **Veri hazırlama araçları kodlandı** (`ai/training/prepare_dataset.py`): COCO→birleşik
    YOLO dönüştürme (sınıf eşleme `COCO_TO_CANONICAL`), veri seti **denetimi** (sınıf dengesi, etiket format
    doğrulama, train/val/test **sızıntı** tespiti, yetim görüntü/etiket) ve `data.yaml`↔`TARGET_CLASSES`
    **tutarlılık** kontrolü. *Neden:* plan.md Bölüm 5 (veri hattı) + Risk 4.1/11'i hayata geçirir; açık
    kaynak havuzunu eğitime hazır hale getirir. *Ölçüm:* 9 yeni saf-mantık testi → **toplam 47 test yeşil**
    (mock); CLI uçtan uca dumanlandı (verify/scaffold/coco/audit). Çevrimdışı, GPU/ağ gerekmez.
  - *(2026-06-06)* **Eğitim hattı güçlendirildi** (`ai/training/train.py`): aşamalı müfredat (ısınma
    omurga-donuk → ana fine-tune → opsiyonel saha-uyarlama, aşamalar `best.pt` ile zincirli), **iki kademe**
    (`--tier normal=yolov8n` / `critical=yolov8s`), düzeltilmiş **export** (onnx / onnx-fp16 / engine-int8;
    INT8 artık kalibrasyon verisi zorunlu — eski `int8` hatası giderildi) ve **`--dry-run`** (planı GPU'suz
    göster). *Neden:* plan.md Bölüm 6.1/3/9. *Ölçüm:* orkestrasyon saf fonksiyonlara ayrıldı → 15 yeni test,
    **toplam 62 test yeşil**; dry-run uçtan uca dumanlandı (3-aşama zincir + INT8 kwargs). Gerçek koşum hâlâ
    ultralytics+GPU ister (Faz 3/4).
  - *(2026-06-06)* **Gerçek-mod pipeline doğrulandı** (`eval/real_smoke.py`): `AI_MODE=real` ile gerçek
    YOLOv8 `Pipeline.process()`'ten uçtan uca geçti — `bus.jpg`'de otobüs→`vehicle` (vtype=bus, conf 0.92),
    insanlar→`person` doğru tespit; renk "mavi". plate/driver kütüphanesi (easyocr/mediapipe) yokken **mock'a
    nazik düştü, sistem ÇÖKMEDİ** (K4 gerçek modda da geçerli). *Ölçüm:* normal+kritik profil çalıştı, mock
    paketi 73 yeşil. Tekrarlanabilir araç eklendi (otomatik teste dahil değil — model/GPU ister).
  - *(2026-06-06)* **Veri indirme yardımcıları kodlandı** (`ai/training/fetch_data.py` + `sources.json`):
    plan Bölüm 4 kaynak tablosu **bildirimsel manifeste** döküldü (9 kaynak); `list`/`coverage`/`validate`
    (ağsız) + `fetch` (Roboflow API / HTTP zip, import-korumalı). Doğrulama: sınıflar ⊆ `TARGET_CLASSES`,
    benzersiz ad, **lisans whitelist** (academic/roboflow → ⚠ teyit, Risk 11), **sınıf kapsama boşluğu**
    tespiti. *Neden:* plan Bölüm 4'ü operasyonel hale getirir; her sınıfın kaynağı var mı görünür.
    *Ölçüm:* 11 yeni test → **toplam 73 yeşil**; CLI dumanlandı (9 kaynak, tüm sınıflar kapsanıyor).
    JSON manifest (PyYAML yok, K-007).
- **Faz 9 — Çoklu-araç genişletme** → BEKLEYEN

---

## 3. Karar Günlüğü

- **K-001 (2026-06-05):** Yeni temel = `cleoanka/teknofest-prototip`.
  *Neden:* şartname/transkriptle birebir 3-parçalı mimari (mobil↔backend↔YZ), çalışan
  QoD tetik motoru ve mobil uygulama hazır; eski proje (`C:\teknofest`) referans kalır.
- **K-002 (2026-06-05):** YZ kolu bizim. Sahiplik: `ai/` + `config/settings.py` (YZ eşikleri) + `eval/`.
- **K-003 (2026-06-05):** **Mock-first korunacak** (`AI_MODE=auto`). Kütüphane yoksa sistem mock'a düşmeli, testler yeşil kalmalı.
- **K-004 (2026-06-05):** Çözüm **genel** olacak (her yer/araç). Tek test videosuna özel çözüm yazılmayacak; gizli test seti farklı araç/açı/hava içeriyor.
- **K-005 (2026-06-05):** Kod **her zaman açıklamalı** yazılacak (Türkçe yorum + docstring + neden-yorumu); her adımda PROGRESS/AGENTS güncellenecek.
- **K-007 (2026-06-05):** Veri araçlarında **PyYAML bağımlılığı eklenmedi**; `data.yaml` sınıf bloğu için
  biçime-özel minik ayrıştırıcı yazıldı. *Neden:* tutarlılık testi mock/CI'da (ultralytics/pyyaml yokken)
  yeşil kalsın (K4). CLI çıktısı Windows'ta çökmesin diye stdout UTF-8'e alındı (R1).
- **K-006 (2026-06-05):** **Git ile sürüm yönetimi + GitHub'a push.** Her tamamlanan adım kendi
  atomik commit'i olur; sıra: değişiklik → `make test` yeşil → PROGRESS güncel → `git commit` (doküman
  dahil) → `git push`. Commit mesajı Türkçe ve `<alan>: <ne> (neden)` biçiminde. Model ağırlığı/video/
  `.venv`/sır commit'lenmez (`.gitignore`). *Neden:* her adım izlenebilir/geri alınabilir olsun, takım
  GitHub üzerinden senkron kalsın. Detay kural: `AGENTS.md` **K7**.

---

## 4. Açık Konular / Riskler (derin kod incelemesinden)

- **R1 — Platform (büyük ölçüde çözüldü, 2026-06-06):** Repo macOS varsayıyor (`run_dev.sh` → MPS, iPhone/Expo).
  Bizim kurulum **Windows + NVIDIA RTX 4070 Laptop (8GB)** (plan "4060" diyordu; gerçek donanım 4070). venv
  yolu `.venv\Scripts`; gerçek modda CUDA doğrulandı (torch 2.6.0+cu124, `cuda.is_available()=True`). Eğitim
  ve çıkarım GPU'da koşuyor (Faz 2/3). `run_dev.sh` (bash) hâlâ Windows'ta doğrudan çalışmaz — PowerShell
  betiği (`run_dev.ps1`) takım tarafında mevcut.
- **R2 — Eğitilmiş model yok:** `cigarette/seatbelt/headphone` COCO'da yok → `driver_state` bu davranışları
  fine-tune'a kadar **üretemez** (kemer kontrolü kodda kasıtlı kapalı). Sigara/kemer demoda çalışmaz.
- **R3 — Olası kırık test:** `tests/test_pipeline_schema.py::test_pipeline_reads_plate_in_critical` mock modda
  `plate.text is not None` bekliyor; mock PlateReader plaka üretmiyor → bu test mock'ta **düşebilir**.
  Windows'ta `make test` ile teyit edilmeli (sandbox'ta PyPI engelli olduğu için koşulamadı).
  *Not (2026-06-05):* `origin/main` bu testi zaten düzeltmiş (driver/passenger ROI + "sahte plaka yok")
  ama **çalışma ağacı uzaktan sapmış/eski**; bkz. R6.
- **R6 — Çalışma ağacı uzaktan sapmış (2026-06-05):** Yerel çalışma ağacı `origin/main`'den **geride/farklı**.
  Kanıt: `origin/main` `ai/schema.py`'de `driver_bbox`/`passenger_bbox` alanlarını içeriyor ve `test_pipeline_schema`
  güncel sürümde; yerel kopyada bunlar yok + `docs/`, `ai/lp_detector.py` vb. siliniş/eski. `make test`'in
  "1 failed" sonucu **eski yerel koda** ait; uzak büyük olasılıkla zaten yeşil. **Karar gerekiyor:** çalışma
  ağacını `origin/main` ile uzlaştır (muhtemelen uzağı baz al). Yeni eklenenler (`ai/plan.md`,
  `ayrıntılıanlatım.md`) ayrı korunmalı.
- **R4 — Tek-araç varsayımı:** Pipeline en büyük bbox'lı birincil aracı işliyor; şartname "tüm araçlar" istiyor.
- **R5 — Hız kalibrasyonsuz:** `speed_calibration_k=900` keyfi; gerçek km/h anlamlı değil (ihlal eşiği için kullanılıyor, o yeterli).
- **R7 — lp_detector HF bağımlılığı (2026-06-06):** `ai/lp_detector.py` (origin/main) plaka dedektör modelini
  `huggingface_hub` ile yüklemeye çalışıyor; kurulu değilse **CV fallback**'e düşüyor (çökme yok, gerçek-mod
  dumanında doğrulandı). Gerçek HF plaka modeli istenirse `pip install huggingface_hub` + model; aksi halde
  CV/heuristik plaka yolu kullanılır.

---

## 5. Sıradaki Adımlar (kısa vade)

### ✅ Tamamlanan (6 Haziran 2026 oturumu)
- Git/GitHub kurulumu + K7 iş akışı (uzak: `cleoanka/teknofest-prototip`, daima fetch+rebase).
- **Veri hazırlama araçları** (`prepare_dataset.py`): COCO→YOLO, audit, data.yaml↔TARGET_CLASSES.
- **Eğitim hattı** (`train.py`): aşamalı müfredat + iki kademe (n/s) + INT8 export + `--dry-run`.
- **Veri indirme** (`fetch_data.py` + `sources.json`): manifest + kapsama/lisans doğrulama.
- **Faz 2/3:** CUDA torch+ultralytics kuruldu, gerçek GPU eğitimi (coco8, yolov8n **72.7 FPS**).
- **Gerçek-mod pipeline dumanı** (`eval/real_smoke.py`): `AI_MODE=real` çökmeden çalışıyor, K4 fallback geçerli.
- Test: **73 yeşil** (mock). Tüm adımlar atomik commit + push'landı.

### ✅ Tamamlanan (6 Haziran — devam oturumu)
- **Gerçek COCO alt-küme eğitimi (Faz 3 tam) → `best.pt` v0.** COCO **val2017** (5000 imaj) indirildi;
  yeni `ai/training/build_coco_subset.py` ile hedef-sınıf içeren imajlara süzülüp train/val'a bölündü
  (**2555 / 639 imaj**, 14269 kutu). `train --tier critical --curriculum` (yolov8s, RTX 4070).
- **Per-sınıf val (mAP50):**

  | model | ALL | vehicle | person | phone |
  |---|---|---|---|---|
  | ısınma (donuk omurga, 5ep) | **0.602** | 0.657 | 0.762 | 0.387 |
  | ana fine-tune (30ep) | 0.481 | 0.506 | 0.683 | 0.254 |

  ⚠ **Bulgu (K-008):** Agresif fine-tune (mosaic=1.0/mixup/scale=0.5 + tam çözme) küçük 2555-imaj
  alt-kümesinde COCO-öneğitimli özellikleri **aşındırdı** → ısınma modeli her sınıfta daha iyi.
  **v0 olarak ısınma `best.pt` seçildi** → `models/yolguvenligi_coco_v0.pt`, `.env`'de `YOLO_MODEL_CRITICAL`.
- **`train.py` taşınabilirlik düzeltmesi:** `_resolve_data_yaml()` data.yaml'deki göreli `path`'i mutlak
  yapar (ultralytics `datasets_dir` import-anı önbelleğini atlar; eskiden gerçek eğitim çökerdi).
- Gerçek-mod doğrulama: pipeline v0 modelini yükleyip çıkarım yapıyor (person tespiti OK).

### ⏭️ Sıradaki (öncelik sırası)
1. **v1 eğitim reçetesi (bulgu K-008'i çöz):** ya hafif augmentation + düşük lr + daha çok freeze ile
   ısınmadan ileri git, ya da daha çok veri (BDD100K/daha fazla COCO) + uzun schedule. Hedef: ana aşama > 0.602.
2. **`eval/evaluate.py` — QoD %40 kanıtı (plan Bölüm 8):** mock kanıt ÇALIŞIYOR (cabin 0→73, bant tasarrufu
   ~%22). Eksik: gerçek `best.pt` v0 ile çalıştırıp sayıyı tazele + per-sınıf mAP'i rapora bağla.
3. **Faz 4 — Gerçek plaka OCR:** `pip install easyocr` (GPU) → gerçek-mod dumanında plate gerçek;
   "34 TC 8532" birikimini taşı. **R7 güncel:** `keremberke/yolov8n-license-plate-detection` HF reposu
   **kaldırılmış** (RepositoryNotFoundError) → lp_detector CV fallback'te; yeni plaka modeli/repo bul.

### 🔧 Açık/temizlik
- `stash@{0}` ("R6: sapmış eski çalışma ağacı") hâlâ duruyor — büyük olasılıkla **atılacak** (`git stash drop`),
  uzak zaten ileride. Atmadan önce `git stash show -p stash@{0}` ile son bir göz at.
- `ayrıntılıanlatım.md` (untracked, yeni) — istenirse ayrı commit'lenecek.
- Ortam: gerçek-mod için `.venv`'de CUDA torch + ultralytics kurulu (mediapipe/easyocr **yok** → o modüller mock).

---

## 6. Haftalık Rapor Formatı (her ajan)

- Bu hafta ne yapıldı?
- Ne çalışıyor (ölçümle)?
- Ne blokluyor?
- Gelecek hafta hedefi?

---

## 7. Çalıştırma Hatırlatması

```
# Backend + web (mock mod yeterli):
AI_MODE=mock  -> kütüphane gerekmez, uçtan uca çalışır
AI_MODE=real  -> ultralytics + easyocr + mediapipe kuruluysa gerçek model

# Test (mock, deterministik):
make test     (Windows: .venv\Scripts\python -m pytest)

# Doğruluk değerlendirmesi (Normal vs Kritik + bant verimliliği):
make eval
```

---

## 8. Git İş Akışı Hatırlatması (K7)

```
# Her tamamlanan adımdan sonra (mock testleri yeşilken):
make test                       # önce yeşil olduğundan emin ol
git pull --rebase               # çakışmayı önle
git add <değişen dosyalar>      # ya da: git add -A
git commit -m "ai: <ne yapıldı> (<neden>)"   # PROGRESS/AGENTS güncellemesi aynı commit'te
git push

# Commit mesajı alanları: ai | config | eval | docs | test | chore
# Commit'lenmez: *.pt model ağırlıkları, videolar, .venv/, .env, sır/token
```
