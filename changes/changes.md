# YZ Sistemi Değişiklik Özeti

**Tarih:** 2026-06-05  
**Versiyon:** 2.0 — Kapsamlı YZ Düzeltmesi

---

## 1. Plaka Tespiti — Tamamen Yenilendi

### Sorun
- EasyOCR'un içe aktarıldığı noktada Python 3.13 SSL sertifika hatası veriyordu.
- Araç bbox'ından elle yapılan kırp, canlı akışta (~640px) plakanın yalnızca ~33px genişlikte görünmesine yol açıyordu — OCR imkânsızlaşıyordu.
- TOGG gibi COCO'nun tanımadığı araçlarda araç tespiti yoktu, dolayısıyla plaka kırpma da yoktu.

### Çözüm (`ai/lp_detector.py` — YENİ)
- **`keremberke/yolov8n-license-plate-detection`** modeli HuggingFace Hub'dan `hf_hub_download()` ile indirilir.
- Model `~/.cache/teknofest/lp_model.pt` konumuna önbelleklenir.
- LP dedektör araç tespitinden **bağımsız** olarak tüm çerçevede çalışır — TOGG tespit edilmese bile plaka bulunabilir.
- Minimum boyut filtresi: 20×8 px (gürültü eleme).

### Çözüm (`ai/plate_ocr.py` — YENİLENDİ)
- `ssl._create_default_https_context = ssl._create_unverified_context` → Python 3.13 SSL hatası giderildi.
- **`super_resolve()`**: LANCZOS4 ile 4× büyütme + bilateral filtre + keskinleştirme kernel.
  - `w < 120px` → 4× süper çözünürlük  
  - `120 ≤ w < 240px` → 2×  
  - `w ≥ 240px` → aynen kullan
- **`ocr_corrections()`**: İl kodu konumunda `O→0, I→1, S→5, B→8`; son rakam grubunda da aynı düzeltme.
- EasyOCR'a `"tr"` dili eklendi.
- `allowlist` ile yalnızca plaka karakterleri (`0-9 A-Z`) okunur.
- Güven eşiği `0.70 → 0.45` (LP dedektör zaten bölgeyi netleştirdi).
- Konsensüs geçmişi: son 8 okuma arasında pozisyon tabanlı oy çokluğu.

---

## 2. Araç Tespiti — TOGG Sorunu

### Sorun
- COCO ön-eğitimli YOLOv8, TOGG tasarımını tanımıyor (ya hiç tespit etmiyor ya da `motorcycle` olarak sınıflıyor).

### Çözüm
- LP dedektör araç tespitinden bağımsız çalıştığından, araç kutusu olmasa bile plaka bulunup OCR yapılabiliyor.
- `pipeline.py` içinde: LP dedektörden plaka bulunup araç yoksa `vehicle.present = True` yapılır, `vtype = "vehicle"` atanır.
- Araç tespiti için fallback: LP sonuçlarından elde edilen plaka bbox'ı çevresinde araç bölgesi varsayılır.

---

## 3. Hız Tahmini — Gürültü Azaltıldı

**Önceki oturumda tamamlandı** (`ai/speed.py`):
- `movement < 0.003` gürültü eşiği → `None` döner.
- `speed < 3.0 km/h` → gösterilmez.
- Efektif FPS bbox hareketi ile orantılı hale getirildi.

---

## 4. Sürücü/Yolcu ROI Ayrımı (`ai/driver_state.py` — YENİLENDİ)

### Sorun
- Tüm araç içi alan sürücü olarak değerlendiriliyordu.
- Yolcu koltuğundaki telefon tehlike olarak işaretleniyordu.

### Çözüm
- **Türkiye LHD (sol direksiyonlu) + önden kamera varsayımı:**
  - Sürücü: araç bbox'ının **sağ yarısı** (kameranın sağı = aracın sola)
  - Yolcu: araç bbox'ının **sol yarısı**
- `driver_roi()` ve `passenger_roi()` static metodları.
- `driver.phone_use = True` → yalnızca sürücü ROI'sinde telefon varsa.
- `driver.passenger_phone = True` → yolcu ROI'sinde telefon varsa (tehlike sayılmaz, kaydedilir).
- MediaPipe Face Mesh artık sürücü ROI kırpmasında çalışıyor (tüm karede değil).

---

## 5. Swerving (Zigzag) Tespiti (`ai/tracking.py` — EKLENDİ)

- `Track.is_swerving(min_frames=10, min_direction_changes=2)` metodu.
- Son N karede araç merkezi x-koordinatının 3-kare hareketli ortalaması hesaplanır.
- Minimum hareket eşiği: 15 piksel (gürültü filtresi).
- En az 2 yön değişikliği → `swerving = True`.
- `risk.py` içinde `zigzag` faktörüne bağlanır (+10 risk puanı).

---

## 6. Ayrı Bounding Box'lar (`ai/schema.py` — GÜNCELLENDİ)

`Vehicle` modeline eklenen alanlar:
- `plate_bbox: Optional[BBox]` — Plaka kutusu (sarı)
- `driver_bbox: Optional[BBox]` — Sürücü ROI (mavi)
- `passenger_bbox: Optional[BBox]` — Yolcu ROI (turuncu)
- `swerving: bool` — Swerving durumu

`DriverState` modeline eklenen alan:
- `passenger_phone: bool` — Yolcu tarafında telefon (tehlike sayılmaz)

---

## 7. Video Test Aracı (`tools/test_video.py` — YENİ)

```bash
# Temel kullanım
python tools/test_video.py project-files/test-verisi/video_3.mp4

# Annotated video çıktısı
python tools/test_video.py video.mp4 --scale 0.5 --out output/result.mp4

# Tüm seçenekler
python tools/test_video.py video.mp4 --every 3 --scale 0.5 --max-frames 100 --json-out results.json
```

- Her N. kareyi tam çözünürlükte işler (hem LP dedektör hem YOLO).
- Annotated video çıktısı: araç (yeşil/kırmızı), plaka (sarı), sürücü ROI (mavi), yolcu ROI (turuncu), kişi (beyaz).
- Terminal'de tespit edilen plakalar, swerving kareleri, risk olayları listelenir.
- JSON özet dosyası (`--json-out`).

---

## 8. Backend — Video Test Endpoint (`backend/main.py` — GÜNCELLENDİ)

- `POST /api/test-video` — Video dosyası yükle (multipart) veya mevcut dosya adı ver.
- `GET /api/test-video/files` — `project-files/test-verisi/` içindeki videoları listele.
- `/output/` static mount → annotated video tarayıcıdan erişilebilir.

---

## 9. Frontend — Bağımsız Kutu Gösterimi (`frontend/app.js` — GÜNCELLENDİ)

- `drawBox()` — düz çizgi, dolgu etiket.
- `drawROI()` — kesikli çizgi (sürücü/yolcu).
- Renk kodlaması:
  - Araç: yeşil `#00e676` (swerving → kırmızı `#ff3333`)
  - Plaka: sarı `#ffee00`
  - Sürücü ROI: mavi `#29b6f6` (kesikli)
  - Yolcu ROI: turuncu `#ffa726` (kesikli)
  - Telefon: kırmızı `#ff4d5e`
  - Kişi: beyaz
- Araç kutusunda: `tip | plaka | hız` etiketi.
- Plaka kutusunda: `PLAKA: 34TC8532` etiketi.
- Sürücü ROI'sinde: `SÜRÜCÜ [TELEFON!]` varsa uyarı.
- Swerving bilgisi araç panelinde gösterilir.

---

## 10. Bağımlılıklar (`requirements.txt` — GÜNCELLENDİ)

```
huggingface_hub>=0.20.0    # keremberke LP modeli için
```

---

## Test — video_3.mp4 (34TC8532)

```bash
# LP modeli indir ve test et
python tools/test_video.py "project-files/test-verisi/video_3.mp4" \
  --scale 0.5 \
  --every 2 \
  --out output/video_3_annotated.mp4

# Beklenen çıktı:
# - "34TC8532" plakasnın en az birkaç karede tespit edilmesi
# - Swerving tespiti (araç zigzag yapıyor)
# - Annotated video: output/video_3_annotated.mp4
```

---

## Dosya Değişiklikleri Özeti

| Dosya | Durum | Açıklama |
|-------|-------|---------|
| `ai/lp_detector.py` | **YENİ** | HuggingFace LP dedektör |
| `ai/plate_ocr.py` | Yenilendi | SSL, süper çözünürlük, düzeltmeler |
| `ai/tracking.py` | Güncellendi | `is_swerving()` metodu |
| `ai/driver_state.py` | Yenilendi | Sürücü/yolcu ROI ayrımı |
| `ai/schema.py` | Güncellendi | plate_bbox, driver_bbox, swerving alanları |
| `ai/pipeline.py` | Yenilendi | LP dedektör + swerving + ROI entegrasyonu |
| `tools/test_video.py` | **YENİ** | Video test CLI aracı |
| `backend/main.py` | Güncellendi | /api/test-video endpoint |
| `frontend/app.js` | Güncellendi | Ayrı bbox renk kodlaması |
| `frontend/index.html` | Güncellendi | Swerving göstergesi |
| `requirements.txt` | Güncellendi | huggingface_hub eklendi |
| `output/` | **YENİ** | Annotated video çıktı klasörü |
