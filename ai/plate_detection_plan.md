# Plaka Tespiti, Crop ve OCR Geliştirme Planı

> TEKNOFEST 2026 · Akıllı Yol Güvenliği  
> Kapsam: `ai/lp_detector.py`, `ai/pipeline.py`, `ai/plate_ocr.py`  
> Durum: Canlı ürün üzerinde aşamalı geliştirme yol haritası

---

## Mevcut Durum (Haziran 2026)

| Bileşen | Durum | Sorun |
|---|---|---|
| Araç tespiti | ✅ YOLOv8 çalışıyor | COCO ön-eğitimli, plaka sınıfı yok |
| LP dedektör | ⚠️ CV fallback aktif | Model indirme başarısız; CV trafik levhasını plaka sanıyordu |
| Pipeline Blok D | ✅ Araç crop'a kısıtlandı | Full frame → araç crop → false positive önlendi |
| OCR | ⚠️ EasyOCR çalışıyor | Karanlık/bulanık karelerde okuma düşük |
| plate_pixel_width | ✅ Set ediliyor | Henüz hız kalibrasyonuna bağlanmadı |

---

## Katman 1 — Plaka Tespiti (Bul)

### 1.1 Dedicated YOLO Plaka Modeli — YOLOv8n-plate `[ÖNCELİK: YÜKSEK]`

**Sorun:** CV fallback geometrik kurallara dayanıyor; yağmur, gece, gölge,
perspektif gibi durumlarda çöküyor. YOLO'nun buna ihtiyacı yok.

**Çözüm:** Küçük, hızlı, yalnızca plaka sınıflı bir `yolov8n` eğit.

```
Veri kaynakları:
  - CCPD (Chinese, ~300K — tespit için iyi genelleşiyor)
  - Roboflow TR Plaka (TR formatı, ~3-10K)
  - Kendi etiketleme: komite videosundan ~300-500 kare (labelImg / Roboflow)

Eğitim hedefi:
  - Tek sınıf: license_plate
  - imgsz: 640
  - mAP@50 ≥ 0.85 hedefi
  - Boyut: ~6MB (yolov8n), çıkarım <10ms (araç crop üzerinde)

Entegrasyon:
  - Eğitilen .pt → LP_MODEL_PATH=/path/to/lp_yolo.pt
  - Pipeline değişmez; lp_detector.py zaten YOLO'yu kullanmaya hazır
```

**Alternatif — Ana YOLO'ya license_plate sınıfı ekle:**  
`TARGET_CLASSES` içinde `license_plate` zaten var (index 5).
Ana model eğitilirken plaka sınıfı da dahil edilirse ayrı LP dedektöre
gerek kalmaz; Blok D'de `detections` içinden `label == "license_plate"`
filtrelenip direkt kullanılır. Bu tek-model yaklaşımı daha verimlidir.

---

### 1.2 Ana YOLO'dan Plaka Sınıfı Kullanımı `[ÖNCELİK: ORTA]`

Ana model fine-tune edildiğinde `license_plate` sınıfını tespit edebilir
hale gelirse Blok D şöyle sadeleşir:

```python
# Blok D alternatif — ayrı LP modele gerek yok
plate_dets = [d for d in detections if d.label == "license_plate"]
if plate_dets and vehicle.bbox:
    best = max(plate_dets, key=lambda d: d.bbox.area)
    vehicle.plate_bbox = best.bbox
    vehicle.plate_pixel_width = round(best.bbox.width, 1)
    # crop → OCR
```

Avantajı: tek YOLO geçişinde hem araç hem plaka bulunur; LP dedektör
süresini tamamen ortadan kaldırır (~10-15ms kazanç).

---

### 1.3 Perspective Correction (Plaka Düzeltme) `[ÖNCELİK: ORTA]`

**Sorun:** Plaka eğimli çekilince OCR başarısı düşüyor.

**Çözüm:** YOLO bbox köşelerini Hough çizgileriyle veya köşe tespiti ile
bulup perspektif dönüşümü uygula; OCR'a düz plaka gönder.

```python
def _deskew_plate(crop: np.ndarray) -> np.ndarray:
    """
    Hough veya köşe tespiti → cv2.getPerspectiveTransform
    → standart 52:11.2 oranına warp
    """
    ...
```

Eklenecek yer: `ai/plate_ocr.py` → `_preprocess_variants()` içine
ek variant olarak veya ayrı `_deskew_plate()` fonksiyonu.

---

## Katman 2 — Plaka Crop (Kesin Sınır)

### 2.1 Tight Crop Padding `[ÖNCELİK: DÜŞÜK — hızlı]`

Tespit bbox'ı plakanın etrafında birkaç piksel boşluk bırakıyor.
OCR için optimal padding: yüksekliğin ~%10'u sağ/sol, ~%5 üst/alt.

```python
def _pad_plate_crop(crop, pad_h=0.10, pad_v=0.05):
    h, w = crop.shape[:2]
    ph, pv = int(h * pad_h), int(w * pad_v)
    return crop[max(0,py-pv):py+h+pv, max(0,px-ph):px+w+ph]
```

---

### 2.2 Plaka Kalite Skoru — En İyi Kareyi Seç `[ÖNCELİK: YÜKSEK]`

**Sorun:** Hareket bulanıklığı olan karelerde OCR başarısız olsa da 2-3
kare önce net bir kare vardı.

**Çözüm:** Plakanın Laplacian keskinlik skoru yüksek olan karelerini
`PlateReader._history`'ye öncelikli gönder.

```python
sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
# Pipeline: son 5 karenin en keskin crop'unu OCR'a gönder
# Mevcut _history mekanizması bunu zaten destekliyor
```

---

### 2.3 Frame Tracking — Aynı Plakayı Takip Et `[ÖNCELİK: ORTA]`

`IOUTracker` araçları zaten takip ediyor. Plaka bbox'ını araç
`track_id`'siyle eşleştirerek:

1. Aynı araçtan gelen plaka crop'larını biriktir (5-10 kare)
2. En keskin crop'u OCR'a gönder
3. Consensus mekanizması birden fazla okumayı birleştirir

Bu `PlateReader._history` deque'ünün zaten yaptığı şeyin pipeline
seviyesinde güçlendirilmiş hali.

---

## Katman 3 — OCR Kalitesi (Oku)

### 3.1 PaddleOCR Entegrasyonu `[ÖNCELİK: ORTA]`

EasyOCR Türk plakaları için iyi ama PaddleOCR özellikle düşük çözünürlüklü
ve perspektifli metinlerde daha iyi sonuç verir.

```python
# PlateReader._resolve() içine
try:
    from paddleocr import PaddleOCR
    # Kullanım: ocr.ocr(crop, cls=False)
    # Sonuç: [[[bbox, (text, conf)], ...]]
```

Strateji: EasyOCR → conf < 0.5 ise PaddleOCR dene; ikisinin en
yüksek güven skorunu kullan.

---

### 3.2 YOLO-Based Karakter Tespiti + CNN OCR `[ÖNCELİK: DÜŞÜK]`

Uzun vadeli hedef: EasyOCR'ı tamamen kaldırıp plakaya özel
hafif bir pipeline kur.

```
1. Küçük YOLO (karakter dedektör):
   - Sınıflar: 0-9, A-Z (Türk seti: 31 harf)
   - imgsz: 128 (plaka crop küçük)
   - Eğitim: CCPD karakter bounding box etiketleri

2. Sıralama: tespit edilen karakterleri x koordinatına göre sırala
3. Sonuç: "34TC8532" formatında birleştir
```

Bu yaklaşım EasyOCR'a göre 10-20x daha hızlı ve çok daha az bellek
kullanır (~2MB model).

---

### 3.3 Super-Resolution Upscale İyileştirmesi `[ÖNCELİK: DÜŞÜK]`

Mevcut `_upscale()` basit bicubic kullanıyor. Real-ESRGAN gibi hafif SR
modelleri küçük plaka crop'larını daha iyi büyütür.

```python
# Seçenek: OpenCV'nin DNN modülü ile hafif SR
# Model: ESPCN_x4.pb (~670KB, CPU'da ~3ms)
sr = cv2.dnn_superres.DnnSuperResImpl_create()
sr.readModel("ESPCN_x4.pb")
sr.setModel("espcn", 4)
upscaled = sr.upsample(crop)
```

---

### 3.4 Karanlık Ortam İyileştirmesi `[ÖNCELİK: YÜKSEK]`

Parkta görülen sorun: plaka pikselleri 20-40 değerinde, CLAHE sonrası
bile OCR güçleşiyor. Committed `plate_ocr.py`'deki gamma correction
bunu kısmen çözüyor ama daha agresif olabilir.

```python
# Gamma dönüşümü + lokal kontrast + adaptive sharpening
mean_lum = cv2.mean(gray)[0]
if mean_lum < 60:       # gece/otopark
    gamma = 0.25        # daha agresif aydınlatma
elif mean_lum < 100:
    gamma = 0.40
else:
    gamma = 1.0         # gündüz, dokunma
```

---

## Katman 4 — Hız Kalibrasyonu (plate_pixel_width Kullan)

### 4.1 Plaka Boyutundan Mesafe Tahmini `[ÖNCELİK: ORTA]`

```
Türk standart plaka: 520mm × 112mm

distance_m = (focal_px × 0.520) / plate_pixel_width

focal_px: kamera odak uzunluğu (piksel cinsinden)
          → tek referans kareden kalibre edilebilir:
            bilinen_mesafe_m = (focal_px × 0.520) / ölçülen_pixel_w
            focal_px = bilinen_mesafe_m × ölçülen_pixel_w / 0.520
```

Uygulama: `ai/speed.py` içine `estimate_distance_from_plate()` fonksiyonu.
`pipeline.py` bunu `vehicle.speed_kmh` hesabına iletir.

Avantajı: Mevcut bbox-alan tabanlı hız tahmini (`speed_calibration_k`)
kesin değil. Plaka boyutu fiziksel sabit (520mm) kullandığı için
kamerayı bir kez kalibre edince tüm videolarda doğru mesafe hesabı verir.

---

## Uygulama Sırası (Önerilen)

| Öncelik | Geliştirme | Etki | Süre |
|---|---|---|---|
| 1 | Ana YOLO'ya `license_plate` sınıfı ekle (eğitim) | Ayrı LP model yok, single-pass | Eğitim süresiyle bağlı |
| 2 | Plaka kalite skoru — en keskin kare seçimi | OCR başarısı %20-30 artış | 1-2 saat |
| 3 | Karanlık ortam gamma agresifliği | Otopark senaryosu kurtarılır | 1 saat |
| 4 | Perspective correction (deskew) | Eğik plakalarda OCR düzelir | 2-3 saat |
| 5 | Plaka boyutundan mesafe (`estimate_distance_from_plate`) | Gerçek hız kalibrasyonu | 2-3 saat |
| 6 | PaddleOCR fallback | EasyOCR başarısız durumlarda | 2-3 saat |
| 7 | YOLO karakter dedektörü | En hızlı OCR, no-dependency | 1-2 gün (eğitim) |
| 8 | Super-resolution (ESPCN) | Küçük plaka crop kalitesi | 1 saat |

---

## Kritik Dosyalar

| Dosya | İlgili geliştirme |
|---|---|
| `ai/lp_detector.py` | YOLO model entegrasyonu, CV fallback |
| `ai/pipeline.py` | Blok D: araç crop, koordinat dönüşümü, plate_pixel_width |
| `ai/plate_ocr.py` | Preprocessing, EasyOCR, PaddleOCR, perspective |
| `ai/speed.py` | Plaka boyutundan mesafe/hız |
| `ai/schema.py` | plate_pixel_width, BBox.width/height (✅ eklendi) |
| `config/settings.py` | lp_model_path, plate_real_width_mm (✅ eklendi) |
| `ai/training/data.yaml` | license_plate sınıfının eğitim verisine dahili |
