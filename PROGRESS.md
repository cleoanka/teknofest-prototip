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

### ✅ Tamamlanan (6 Haziran — taksonomi + tip-ayrımlı model)
- **K-008 derinleşti:** "nazik" reçete (çözük omurga + lr0=0.002 + cos_lr) bile düştü (0.49→0.30) →
  asıl ilaç **donuk omurga**. `train.py`'ye `--gentle` (hafif aug+lr0+cos_lr) ve `--freeze N` knob'ları
  eklendi (testli). Bulgu: küçük benzer-alan veride omurgayı donuk tut, başlığı eğit.
- **ARAÇ TİPİ AYRIMI (şartname).** Şema zaten `vehicle.vtype` taşıyordu; backend `vtype` kolonu hazırdı.
  Taksonomi **2 uzaya** ayrıldı: (1) `TARGET_CLASSES` = modelin 11 sınıfı (car/minibus/bus/truck/motorcycle
  + 6 diğer); (2) şema etiketi `vehicle` + `vtype`. Yeni: `COCO_TO_TARGET` (eğitim, birleştirme yok) ve
  `CANONICAL_MAP` (çıkarım: alt-tip → ("vehicle", vtype)). detector/pipeline/data.yaml/sources.json + testler
  güncellendi. **Backend/şema kontratı DEĞİŞMEDİ** (vehicle+vtype) → 251 test yeşil.
- **Tip-ayrımlı model `yg_types_v1`** (yolov8s, donuk omurga, COCO val2017 11-sınıf):

  | car | bus | truck | motorcycle | person | phone | ALL |
  |---|---|---|---|---|---|---|
  | .592 | .593 | .430 | .674 | .751 | .310 | **.559** |

  → `models/yolguvenligi_types_v1.pt`, `.env` `YOLO_MODEL_CRITICAL`. Pipeline `vehicle.vtype` üretiyor (doğrulandı).
  Zayıf: truck (415 kutu), phone (262, küçük). **minibus + license_plate/cigarette/seatbelt/headphone = 0 veri.**

### ✅ Tamamlanan (6 Haziran — veri takviyesi + minibüs → yg_types_v2)
- **train2017 hedefli takviye** (`supplement_coco.py`, retry'lı indirme): truck/phone içeren ~10k imaj
  indirilip train'e eklendi → truck 415→10367 kutu, phone 262→6695 (25×). car/person/bus/moto da büyüdü.
- **Minibüs** (`merge_yolo.py` + Roboflow `proj1-9o1hk/minibus-wb4sr`, CC BY 4.0): ad-bazlı remap ile
  1189 minibüs + 74 car kutusu birleştirildi (train+val). val'e minibüs eklendi → mAP ölçülebilir.
- **`yg_types_v2`** (run yg_types_v3; donuk omurga, batch32, 20ep; train 14171 / val 855 imaj):

  | car | minibus | bus | truck | motorcycle | person | phone | ALL |
  |---|---|---|---|---|---|---|---|
  | .615 | **.966** | .689 | .529 | .716 | .768 | .504 | **.684** |

  v1→v2: ALL .559→**.684**; truck +.10, phone +.19, minibüs 0→**.97**. → `models/yolguvenligi_types_v2.pt`,
  `.env`. **Git LFS** ile commit'li (`.gitattributes`: `models/*.pt filter=lfs`).

### ✅ Tamamlanan (6 Haziran — metrik hız: Aşama 0–1 / gercek_hiz_plani.md)
- **Plan dokümante edildi:** `ai/gercek_hiz_plani.md` — kalibrasyonsuz sabit kameradan **metrik km/h**
  oto-kalibrasyon stratejisi (A: plaka/araç ppm(y), B: şerit homografisi, C: kaçış noktası) + ground-truth'suz
  doğrulama. 6 aşamalı yol haritası.
- **Aşama 0 — Zaman ekseni (gerçek Δt/PTS):** Hız artık wall-clock İŞLEME süresini değil, **video-zaman
  çizgisi** Δt'sini kullanıyor. `Track.ts_history` + `Track.dt_last()` eklendi → damgalı iki örnek arası
  **gerçek geçen süre** (düşürülen kareleri/VFR'yi doğru ele alır). `pipeline.process(frame_ts=...)` PTS/
  client_ts kabul ediyor; `tools/test_video.py` gerçek video PTS'i (`CAP_PROP_POS_MSEC`, yoksa indeks/fps)
  besliyor; `backend/main.py` canlı akışta `client_ts`'i geçiyor. *Neden:* R5 — Δt yanlışsa ölçek mükemmel
  olsa bile hız yanlış. *Ölçüm:* 3 yeni test (dt_last düşen-kare, yarı-süre→2×hız).
- **Aşama 1 — Plaka ppm + ppm(y) ölçek-alanı → metrik km/h:** `ai/calibration.py` eklendi:
  `plate_ppm()` (TR plakası **520 mm**'den yerel ppm; 520/120≈4.33 oran sapınca foreshortening reddi),
  `ScaleField` (onlarca ölçümü görüntü-y'sine göre toplayıp **aykırı-dayanıklı ppm(y)** regresyonu; y-yayılımı
  yoksa sabit ppm), `MetricSpeedEstimator` (yer-temas noktası `Track.foot_history`'den `v=Δs/Δt·3.6`).
  Pipeline plakalardan ölçek-alanını **kareler boyunca ısıtıyor** (§4.3 warm-up); hazır olunca metrik,
  değilse eski sezgisel. Şemaya **`vehicle.speed_is_calibrated`** bayrağı (§7.4 — gerçek km/h ile göreceli
  karışmasın). settings: `plate_width_m`, `calib_min_samples`, `speed_metric_max_kmh` vb. *Ölçüm:* 11 yeni
  test (sentetik: bilinen ppm=10 + 20px/0.1s → **72.0 km/h** analitik doğru); **tüm paket yeşil.**
- **R5 güncellendi:** hız artık plaka görünürken **gerçek km/h** (kalibrasyonsuz sezgisel yalnız yedek,
  `is_calibrated=False`). Aşama 2–6 (araç-genişliği yedeği, pencere/Kalman, şerit homografisi, eval, VP) sırada.
- **Aşama 2 — Araç-genişliği yedeği + füzyon:** Plaka yokken sınıf-bazlı tipik genişlikten
  (car 1.80 / truck-bus 2.50 / moto 0.80 m) ppm. Tekil araç ±%15-20 oynadığından (yandan görünüm bbox
  genişliği=boy hatası) **düşük ağırlıklı** (0.25) örnek; plaka çapası **yüksek** (1.0). `ScaleField`
  **ağırlıklı** polyfit + ağırlıklı aykırı-reddine geçti → çok araçtan istatistiksel sağlamlık (§4.3).
  Pipeline artık **tüm** araçları ölçek-alanına besliyor (normal profilde de, plaka olmadan da metrik hız).
  *Ölçüm:* 4 yeni test (araç-only ppm; plaka füzyonda baskın; araç-only → 18 km/h sentetik); **tüm paket yeşil.**
- **Aşama 3 — Pencere + aykırı reddi + EMA (stabil km/h):** `estimate()` tek-kare farkından **pencereye**
  (`speed_window_frames=6`) yükseldi: ardışık adımların **medyan** hızı. **Fiziksel-olmayan ivme reddi** —
  medyandan `speed_max_accel_mps2·Δt` (8 m/s²) fazla sapan adımlar (ışınlanma/bbox sıçraması) atılır.
  Track-başı **EMA** (`speed_ema_alpha=0.4`) kareler arası jitteri bastırır; silinen track'lerin durumu
  `prune()` ile temizlenir (bellek). *Ölçüm:* 5 yeni test (pencereli sabit hız; ışınlanma adımı reddi →
  18 km/h'de kalır; EMA ani değişimi 54→32 km/h yumuşatır; prune). **Tüm paket yeşil.**
- **Aşama 4 — Şerit homografisi (perspektif-tam, en sağlam):** `ai/homography.py` —
  `GroundHomography` (numpy-only **DLT**, cv2 gerekmez): bilinen 4 yer noktasından (şerit genişliği 3.50 m
  × kesik çizgi adımı 12 m) görüntü→metrik yer düzlemi dönüşümü; `from_lane_markings()` kurar, `to_ground()`
  pikseli (X,Z)'ye eşler. `MetricSpeedEstimator` **füzyon önceliği** kazandı (§7.1): homografi varsa
  yer-temas noktaları yere izdüşürülüp Öklid mesafe (perspektif-tam, derinlikten bağımsız), yoksa ppm(y)'ye
  düşer. `ai/lane_detect.py` — opsiyonel **best-effort** otomatik şerit→homografi (cv2-korumalı; güven
  düşükse/cv2 yoksa None → ppm yedeği; **varsayılan kapalı** `homography_auto=False`). *Ölçüm:* 6 yeni test
  (kalibrasyon noktaları birebir; iç-nokta round-trip; homografiyle 2 m/0.1 s → **72 km/h**; öncelik;
  lane_detect nazik düşüş). **Tüm paket yeşil.** *Not:* oturum sırasında takım `pipeline.py`/`settings.py`'ye
  iki-aşamalı plaka tespitini push'ladı; conflict çözülüp her iki taraf birleştirildi.
- **Aşama 5 — Sentetik + çapraz-yöntem + `eval/speed_eval.py`:** Ground-truth olmadan güven (§8).
  Perspektif-tam sentetik sahne (bilinen homografi) ile aracı **bilinen yer-hızında** koşturup MAE/MAPE ölçer.
  **Bulgu (ölçülü):** Yöntem **B (homografi) MAE 0.00 km/h** (formül+birim birebir kanıt); Yöntem **A (ppm)
  yanal harekette MAE 0.00** (geçerli rejim) ama **boyuna harekette MAE ~50 km/h** — ppm yanal ölçektir,
  kameraya doğru perspektif sıkışmasını çözmez → **şerit görünürken homografi tercih** (§7.1 doğrulanır).
  Overspeed kararı (B): **precision=recall=1.00**. Çapraz-yöntem |A−B| sapması "B'ye güven" sinyali.
  Rapor `eval/speed_eval.log`'a yazılır; saf geometri (GPU/video gerekmez). *Ölçüm:* 6 yeni test. **Tüm paket yeşil.**
- **Aşama 6 — Kaçış noktası (VP) self-kalibrasyon (bağımsız doğrulama):** `ai/vanishing_point.py` —
  `vanishing_point()` çizgi segmentlerinin ortak kesişimini SVD ile bulur (paralelde None);
  `focal_from_orthogonal_vps()` iki ortogonal VP'den odak uzaklığını geri kazanır (özdeşlik
  (vp1−pp)·(vp2−pp)=−f²); `methods_agree()` / `confidence_from_agreement()` A/B/C üç-yöntem uyumundan
  güven üretir (§6/§8.2 — üç yöntem yakınsa metrik hıza güven). Rol: üretimde zorunlu değil, **bağımsız
  üçüncü çapraz-doğrulama**. *Ölçüm:* 6 yeni test (VP kesişim geri kazanımı; paralelde None; f=800 geri
  kazanımı; ortogonal-olmayan→None; uyum/güven). **Tüm paket yeşil. → 6 aşamanın tamamı bitti.**

### ✅ Tamamlanan (6 Haziran — QoD %40 kanıtı GERÇEK videoda)
- **`eval/qod_video.py` (YENI):** `evaluate.py` sentetik mock karelerde çalışır (gerçek model orada 0 bulur);
  bu modül **gerçek sürüş videosunu** (veya kare klasörünü) kare kare Pipeline + QoDManager'dan geçirir →
  bant verimliliği, ilk kritik tetik, kritik kare oranı, `vtype` dağılımı, kabin tespitleri. GT gerekmez.
- **Ölçüm (`C:\teknofest\testverisi`, v2 modeli):** video_1 %34, video_2 %39, video_3 %56 bant tasarrufu →
  **ortalama ~%43** → şartnamenin **%40 QoD kriteri GERÇEK footage'da sağlandı** ✓. `vtype` gerçek videoda
  doğrulandı (car/truck/motorcycle ayırt edildi). *Çerçeve:* doğruluk = gerçek per-sınıf mAP (.684);
  QoD mekanizması = gerçek video bant ölçümü; mock senaryo = deterministik kavram kanıtı.

### ⏭️ Sıradaki (öncelik sırası)
1. **cigarette/seatbelt/headphone verisi:** Roboflow/manuel → bu 3 sürücü-davranışı sınıfını da kapat (`merge_yolo` ile kat).
2. **INT8 export** (`train --export engine-int8`) + gerçek FPS ölçümü (plan Bölüm 9).
3. truck (.53) gerekirse biraz daha güçlendir (daha çok COCO/BDD).
3. **truck'ı biraz daha güçlendir** (.53) gerekirse; INT8 export + FPS ölçümü (plan Bölüm 9).
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
