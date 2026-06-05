# YZ Sistemi Değişiklik Özeti

**Son güncelleme:** 2026-06-05  
**Versiyon:** 2.1 — OCR İyileştirmesi + CLAHE + EasyOCR Modelleri

---

## Versiyon 2.1 Değişiklikleri (2026-06-05 — Bu Oturum)

### Plaka OCR İyileştirmeleri (`ai/plate_ocr.py`)
- **`super_resolve()` → gamma + CLAHE eklendi:** Ortalama parlaklık < 80 olan kırpmalara (yeraltı otoparkı vb.) önce gamma düzeltmesi (γ=0.35), ardından 4× büyütme ve CLAHE uygulanır. Bu sayede video_3 gibi karanlık sahnelerde de plaka okunabilir hale gelir.
- **`ocr_corrections()` genişletildi:** `J→3`, `D→0`, `Q→0`, `U→0` eklendi. EasyOCR'un "J4UC8532" okuması düzeltilerek "34TC8532" elde edilir.
- **Güven eşiği `0.45 → 0.30`:** Karanlık videolarda EasyOCR güveni daha düşük çıkıyor; eşik düşürüldü, konsensüs mekanizması çok-kare ortalaması ile doğruluğu koruyor.

### Plaka Kırpma Genişletildi (`ai/pipeline.py`)
- `_fallback_plate_crop()` içinde yatay alan `%15-%85 → %5-%95`, dikey alan `%58-%98 → %50-%99` yapıldı. Bu sayede plakanın araç kutusunun kenarlarına yakın olduğu durumlar da yakalanıyor.

### CV LP Dedektör — CLAHE Ön İşleme (`ai/lp_detector.py`)
- `_detect_cv()` tamamen yenilendi. Ham piksel parlaklığı yerine **CLAHE ön işlemli görüntü** üzerinde çalışıyor:
  - **Yöntem 1:** CLAHE görüntüsünde sabit eşik (140–200)
  - **Yöntem 2:** Otsu adaptif eşik
  - **Yöntem 3:** Canny kenar + dilate + kontur
- Yeraltı otoparkı (ortalama parlaklık ~29) gibi aşırı karanlık sahnelerde sabit eşik yerine yerel kontrast kullanılıyor.

### EasyOCR Modelleri — Manuel İndirildi
- `craft_mlt_25k.pth` (79 MB) ve `english_g2.pth` (14 MB) `~/.EasyOCR/model/` klasörüne indirildi. Artık ilk çalıştırmada otomatik indirme beklenmiyor.

---

## Versiyon 2.0 Değişiklikleri (Önceki Oturum)

### 1. Plaka Tespiti — Tamamen Yenilendi

**Sorun:** EasyOCR Python 3.13 SSL hatası, araç bbox'ından kırpılan ~33px plaka OCR için çok küçük, TOGG COCO'da tanınmıyor.

**Çözüm (`ai/lp_detector.py` — YENİ):**
- `keremberke/yolov8n-license-plate-detection` modeli HuggingFace Hub'dan indirilir (401 → CV fallback).
- LP dedektör araç tespitinden **bağımsız** olarak tüm çerçevede çalışır.

**Çözüm (`ai/plate_ocr.py` — YENİLENDİ):**
- SSL hatası giderildi (modül seviyesinde yama).
- `super_resolve()`: LANCZOS4 4× büyütme + bilateral + keskinleştirme.
- `ocr_corrections()`: Il kodu ve sayı bloğu düzeltmeleri.
- Konsensüs geçmişi: 8 kare oy çokluğu.

---

### 2. Swerving (Zigzag) Tespiti (`ai/tracking.py`)

- `Track.is_swerving()` metodu.
- **Kriter 1:** Son 12 karede ≥ 2 yön değişimi (zigzag).
- **Kriter 2:** Son 15 karede > 350px yanal hareket (şerit değişimi / manevra).
- video_3.mp4'te doğrulandı: TOGG 946px lateral hareket → swerving ✓

---

### 3. Sürücü/Yolcu ROI Ayrımı (`ai/driver_state.py`)

- Türkiye LHD + önden kamera: sürücü aracın sol tarafı (kameranın sağı).
- `driver_roi()` ve `passenger_roi()` static metodları.
- Yalnızca sürücü bölgesindeki telefon tehlike olarak işaretlenir.
- `passenger_phone` alanı eklendi (kayıt amaçlı, tehlike değil).

---

### 4. Ayrı Bounding Box'lar (`ai/schema.py`)

`Vehicle`:
- `plate_bbox` — Plaka kutusu (sarı)
- `driver_bbox` — Sürücü ROI (mavi kesikli)
- `passenger_bbox` — Yolcu ROI (turuncu kesikli)
- `swerving: bool`

`DriverState`:
- `passenger_phone: bool`

---

### 5. Video Test Aracı (`tools/test_video.py` — YENİ)

```bash
python tools/test_video.py "project-files/test-verisi/video_3.mp4" --every 2 --out output/result.mp4
```

---

### 6. Backend — Video Test Endpoint (`backend/main.py`)

- `POST /api/test-video`
- `GET /api/test-video/files`
- `/output/` static mount

---

### 7. Frontend — Bağımsız Bbox Gösterimi (`frontend/app.js`)

| Nesne | Renk | Çizgi |
|-------|------|-------|
| Araç (normal) | `#00e676` yeşil | Düz |
| Araç (swerving) | `#ff3333` kırmızı | Düz |
| Plaka | `#ffee00` sarı | Düz |
| Sürücü ROI | `#29b6f6` mavi | Kesikli |
| Yolcu ROI | `#ffa726` turuncu | Kesikli |
| Telefon | `#ff4d5e` kırmızı | Düz |

---

## Dosya Değişiklikleri Özeti

| Dosya | Durum | Açıklama |
|-------|-------|---------|
| `ai/lp_detector.py` | **YENİ** | CLAHE tabanlı CV LP dedektör + HuggingFace fallback |
| `ai/plate_ocr.py` | Yenilendi | Gamma+CLAHE, genişletilmiş düzeltmeler, eşik 0.30 |
| `ai/tracking.py` | Güncellendi | `is_swerving()` — zigzag + yanal hareket |
| `ai/driver_state.py` | Yenilendi | Sürücü/yolcu ROI ayrımı |
| `ai/schema.py` | Güncellendi | plate_bbox, driver_bbox, swerving, passenger_phone |
| `ai/pipeline.py` | Yenilendi | LP dedektör + swerving + genişletilmiş kırpma |
| `tools/test_video.py` | **YENİ** | Video test CLI aracı |
| `backend/main.py` | Güncellendi | /api/test-video endpoint |
| `frontend/app.js` | Güncellendi | Ayrı bbox renk kodlaması |
| `frontend/index.html` | Güncellendi | Swerving göstergesi |
| `requirements.txt` | Güncellendi | huggingface_hub eklendi |
| `output/` | **YENİ** | Annotated video çıktı klasörü |
