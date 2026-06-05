# YZ Kolu Rehberi — Yapay Zeka & Görüntü İşleme

> Bu belge YZ kolunda çalışanlar için yazıldı. Nesne tespiti, plaka okuma,
> hız tahmini, sürücü durumu analizi ve risk skorlamasını açıklıyor.

---

## Sen Ne Yapacaksın?

YZ kolu projenin "göz ve beyin" kısmıdır. Kameradan gelen görüntüyü alıp şu
soruları cevaplarsın:

- Bu karede araç var mı? Nerede?
- Plaka ne yazıyor?
- Araç ne hızla gidiyor?
- Sürücü telefon tutuyor mu?
- Genel tehlike skoru kaç?

Bu cevaplar backend'e iletilir, o da ön yüze iletir.

---

## Önce Bunları Öğren (Sıfırdan Başlıyorsan)

Hepsini bütünüyle öğrenmene gerek yok; projeyi anlayacak kadar yeterlisi:

1. **Python temelleri** — değişken, fonksiyon, sınıf, modül import
   - Kaynak: [python.org/about/gettingstarted](https://www.python.org/about/gettingstarted/)

2. **NumPy temelleri** — `np.array`, indexleme, slice, boyutlar (shape)
   - Görüntüler aslında üç boyutlu NumPy dizisidir: `(yükseklik, genişlik, 3-kanal-BGR)`
   - Kaynak: NumPy'ın kendi "Quickstart" belgesi

3. **OpenCV temelleri** — görüntü okuma, renk dönüşümü, dikdörtgen çizme
   - Kaynak: `cv2` kütüphanesi, birkaç YouTube videosu

4. **YOLO kavramı** — nesne tespiti nasıl çalışır, bounding box nedir
   - Ultralytics'in resmi dökümantasyonu yeterli

---

## Görüntü Nasıl Çalışır? (Çok Temel)

Bir görüntüyü bilgisayar sayılar olarak görür. Her piksel (nokta) için 3 sayı
vardır: **Mavi**, **Yeşil**, **Kırmızı** (BGR sırası — OpenCV'nin alışkanlığı).

```
640 piksel genişlik × 480 piksel yükseklik × 3 kanal = 921.600 sayı
```

Bu sayıların her biri 0-255 arası. 0 = siyah, 255 = en parlak.

Biz kameradan gelen bu devasa sayı tablosunu `pipeline.py`'e sokuyoruz,
o da içinden "araç" nerede diye buluyor.

---

## YZ Bileşenleri (ai/ Klasörü)

### 1. `ai/detector.py` — Araç Tespiti

Bu dosya YOLOv8 modelini yönetir.

**YOLOv8 Nedir?**

YOLO = "You Only Look Once". Adı garip ama anlamı güzel: Görüntüye bir kez
bakıp içindeki tüm nesneleri aynı anda buluyor. Çok hızlı.

Nasıl çalışır (basitleştirilmiş):
1. Görüntüyü küçük karelere böler (grid)
2. Her kare için "burada nesne var mı, varsa ne?" diye sorar
3. Cevap olarak dikdörtgen koordinatları + sınıf adı + güven skoru döner

```python
# Tipik YOLO çıktısı:
# label="car", bbox=(x1=120, y1=80, x2=380, y2=350), confidence=0.92
```

Biz COCO veri setiyle ön-eğitimli (hazır) bir model kullanıyoruz.
COCO 80 farklı nesne sınıfı biliyor: araba, kamyon, otobüs, insan, telefon vs.

**İki Model Var:**
- `yolov8n.pt` (nano) → Normal mod. Küçük, hızlı, daha az detay
- `yolov8s.pt` (small) → Kritik mod. Biraz büyük, daha doğru

**Sınıf Haritalama:**
COCO'da "car", "truck", "bus" gibi ayrı sınıflar var. Biz hepsini "vehicle"
olarak birleştiriyoruz. Bu harita `config/settings.py`'de:

```python
COCO_TO_CANONICAL = {
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "person": "person",
    "cell phone": "phone",
}
```

**Mock Modu:**
Ultralytics kurulu değilse `MockDetector` devreye girer. Bu gerçek YZ değil,
piksel parlaklığına bakarak "en parlak bölge araç olsun" diyen basit bir kod.
Üretim için değil, sistemin çalışabilirliğini test etmek için.

---

### 2. `ai/tracking.py` — Araç Takibi

Her karede araç tespiti yapılıyor. Ama "bu karede gördüğüm araçla önceki
karede gördüğüm aynı araç mı?" sorusu takip (tracking) ile çözülür.

**IOU (Intersection over Union) Takibi:**

İki karedeki dikdörtgenler ne kadar örtüşüyor?

```
IOU = Örtüşme Alanı / Birleşme Alanı
```

Örtüşme %50'nin üstündeyse → aynı araç, aynı `track_id` ver.
Örtüşme yoksa → yeni araç, yeni `track_id`.

Takibin önemi: Hız hesaplaması için aynı araçta önceki ve şimdiki konumu
bilmemiz gerekiyor. Track olmadan "bu araç hareket etti mi?" bilemeyiz.

---

### 3. `ai/speed.py` — Hız Tahmini

Gerçek hız tespiti için radar veya GPS gerekir. Biz olmayan şeyle çalışıyoruz:
**piksel hareketi**.

**Yöntem:**

Bir araç yaklaştıkça kameradaki bbox'ı büyür. Uzaklaştıkça küçülür.
Bu büyüme/küçülme oranından hız tahmini yapıyoruz.

```python
# Alan bileşeni: bbox'ın görüntü içindeki oranı nasıl değişiyor?
da = |alan_şimdi - alan_önce| / toplam_görüntü_alanı

# Merkez bileşeni: bbox'ın merkezi kaç piksel kaydı?
dc = mesafe(merkez_şimdi, merkez_önce) / köşegen

# İkisinin büyüğünü al (bazen araç direkt geliyor, merkez oynamıyor ama bbox büyüyor)
movement = max(da, dc)

# Kalibrasyonlu hız:
speed_kmh = K * movement * (fps / 30)
```

`K = 900.0` bizim kalibrasyon sabitimiz. Bu değer gerçek sahada bir araçla
ölçülerek netleştirilir. Şu an deneysel.

**Önemli Sınırlama:** Bu yöntem yaklaşık bir tahmintir. Kameraya dik gelmeyen
araçlarda hata yapar. Gerçek sistemlerde LIDAR veya radar kullanılır.

---

### 4. `ai/plate_ocr.py` — Plaka Okuma

**OCR Nedir?**
Optical Character Recognition = görüntüdeki yazıyı metne çevirme.

Plaka okuma iki aşamadan oluşur:

**Aşama 1: Plaka Bölgesini Bul**
`pipeline.py`'de araç bbox'ının alt %40'ı plaka bölgesi olarak kesilir:

```python
# Araç bbox'ının alt bölgesi (plaka genelde alttta)
px1 = x1 + %20
px2 = x2 - %20
py1 = y1 + %60
py2 = y2
crop = frame[py1:py2, px1:px2]
```

**Aşama 2: OCR**

`PlateReader` sınıfı bu crop'ı üç farklı varyanta çevirir:
- Orijinal görüntü
- CLAHE kontrast artırma (karanlık/parlak bölgeleri dengeler)
- Tersine çevrilmiş (bazen ters arka plan daha iyi okunur)

Her varyanta EasyOCR çalıştırılır. En iyi sonuç seçilir.

**Konsensüs:**
Son 8 okumayı tutar. Her pozisyonda en çok hangi harf çıkmış? Onu seçer.
Bu, tek karedeki yanlış okumayı dengeler.

**Türk Plaka Formatı Kontrolü:**
```
^(0[1-9]|[1-7][0-9]|8[01])[A-Z]{1,3}[0-9]{2,4}$
```
Yani: 2 rakam (il kodu) + 1-3 harf + 2-4 rakam. Geçersiz format → gösterme.

**Güven Eşiği:** 0.70 altında güvenle okunan plakalar gösterilmez.

---

### 5. `ai/driver_state.py` — Sürücü Durumu

Sürücünün tehlikeli davranışlarını tespit eder.

**Yorgunluk Tespiti (MediaPipe):**

Google'ın MediaPipe kütüphanesi yüzde 468 nokta (landmark) tespit eder.
Göz çevresindeki 6 noktanın konumundan **EAR (Eye Aspect Ratio)** hesaplanır:

```
EAR = (|P2-P6| + |P3-P5|) / (2 × |P1-P4|)
```

Göz açıkken EAR ~0.30, kapanınca ~0.10'un altına düşer.

**PERCLOS** (Percent of Eyelid Closure): Son 30 karede kaçında göz kapalıydı?
%40 üzeri → yorgun sürücü uyarısı.

**Telefon/Sigara/Kemer:**
- YOLO "phone" tespit ettiyse ve araç içinde sürücü bölgesiyle örtüşüyorsa → telefon kullanımı
- `seatbelt` ve `cigarette` sınıfları şu an COCO modelinde yok → fine-tune sonrası aktif olacak

**Sürücü ROI (Region of Interest):**
Araç bbox'ının sol-üst %55 × %75 bölgesi sürücü kabini kabul edilir.
Bu bölgede phone tespit edilirse telefon kullanımı sayılır.

---

### 6. `ai/risk.py` — Risk Skoru

Tüm tespitler tek bir 0-100 risk skoruna dönüştürülür:

| Durum | Puan |
|-------|------|
| Telefon kullanımı | +40 |
| Yorgunluk (PERCLOS) | +30 |
| Sigara | +20 |
| Hız aşımı (>50 km/h) | +15 |
| Emniyet kemeri yok | +15 |
| Zigzag | +10 |
| Kulaklık | +5 |

Risk seviyeleri:
- 0-29 → **LOW** (düşük)
- 30-59 → **MEDIUM** (orta)
- 60-84 → **HIGH** (yüksek)
- 85-100 → **CRITICAL** (kritik)

---

### 7. `ai/qod_trigger.py` — Ne Zaman Bant Artırılır?

Bu dosya projenin **%40 puanını** doğrudan etkileyen en kritik bileşen.

500 milisaniyede bir 5 koşul kontrol edilir:

| Koşul | Ne Anlama Geliyor? |
|-------|--------------------|
| **A** | Araç bbox'ı hızla büyüyor (araç yaklaşıyor) |
| **B** | Tespit güveni düşük (model emin değil) |
| **C** | Plaka bölgesi var ama OCR güveni düşük |
| **D** | Araç ROI çizgisini geçti (okuma menzilinde) |
| **E** | Nesne tespiti sınır güvende (ne var ne yok) |

Bu koşullardan **en az biri** iki ardışık döngüde pozitif çıkarsa → Kritik moda geç.
Kritik modda:
- CAMARA QoD API'ye "bant artır" isteği gönderilir
- Daha ağır YOLO modeli devreye girer
- Plaka OCR aktif olur

Bırakma (Normal moda dönüş):
- Yeterli güven sağlandı (iş bitti)
- Oturum 5 saniyeyi aştı (güvenli süre doldu)
- Araç ROI dışına çıktı (araç uzaklaştı)

---

### 8. `ai/pipeline.py` — Hepsini Birleştiren Orkestratör

Her kare geldiğinde sırayla çalışır:

```
Kare Geldi
    │
    ▼
[A] Araç tespiti (YOLO)
    │
    ▼
[B] Takip (IOU tracker → track_id)
    │
    ▼
[C] Hız tahmini
    │
    ▼
[D] Plaka OCR (sadece kritik modda)
    │
    ▼
[E] Sürücü durumu
    │
    ▼
[F] Risk skoru
    │
    ▼
FrameResult + TriggerContext döner
```

---

## `ai/schema.py` — Veri Tipleri

Tüm YZ bileşenlerinin kullandığı veri yapıları burada tanımlı.

```python
class Detection:        # Tek bir tespit (label, bbox, güven)
class BBox:             # Dikdörtgen koordinatları (x1, y1, x2, y2)
class PlateResult:      # Plaka metni + güven + geçerlilik
class DriverState:      # phone_use, fatigue, no_seatbelt...
class RiskAssessment:   # score (0-100), level, factors listesi
class Vehicle:          # plate + speed + vtype + color + bbox
class FrameResult:      # Tek karenin tüm sonucu
class QoDStatus:        # Mevcut bant + mod + oturum bilgisi
```

---

## `ai/training/` — Fine-Tune Sistemi

COCO ön-eğitimli model araç ve telefonu biliyor ama "sigara", "kemer", 
"kulaklık" gibi sınıfları bilmiyor. Bunlar için özel eğitim gerekiyor.

Komite kendi araç/etiket verisini paylaştığında:

1. `ai/training/prepare_dataset.py` ile veriyi hazırla
2. `ai/training/data.yaml`'ı güncelle (sınıf isimleri)
3. `python -m ai.training.train` ile eğit

Eğitim sonucu `.pt` model dosyası üretilir. Bu dosyayı `config/settings.py`'de
`yolo_model_critical` olarak tanımla.

---

## Geliştirme Sürecinde Yapman Gerekenler

### Kodu Test Etmek

```bash
# YZ'yi test eden dosyalar:
make test
# veya spesifik:
.venv/bin/python -m pytest tests/test_pipeline_schema.py -v
.venv/bin/python -m pytest tests/test_qod_trigger.py -v
.venv/bin/python -m pytest tests/test_risk.py -v
.venv/bin/python -m pytest tests/test_speed.py -v
```

### Doğruluk Değerlendirmesi

```bash
# Mock veri üret + Normal vs Kritik karşılaştır
make eval
```

Bu komut `eval/evaluate.py`'yi çalıştırır. Sentetik kareler üzerinde tespitlerin
ne kadar doğru olduğunu raporlar.

### Bir Şeyi Değiştirirken Dikkat

1. `ai/schema.py` değişirse → backend de güncellenmeli (FrameResult alanları)
2. Risk ağırlıkları `config/settings.py`'de → oradan değiştir, her yerde etki eder
3. Model yolları `config/settings.py`'de → `yolo_model_normal` ve `yolo_model_critical`

---

## Sık Karşılaşılan Sorunlar

**Soru: "YOLOv8 model inmiyor, hata alıyorum"**
Cevap: İlk çalıştırmada Ultralytics internet'ten modeli indirir. Bağlantın varsa bekle.
Yoksa AI_MODE=mock ile çalış: `AI_MODE=mock ./run_dev.sh`

**Soru: "MediaPipe import hatası"**
Cevap: `pip install mediapipe==0.10.35` (Python 3.13 için bu sürüm)

**Soru: "EasyOCR çok yavaş"**
Cevap: GPU yoksa CPU'da çalışır, yavaş. Mac Apple Silicon'daysan MPS desteği var:
`pip install torch torchvision` ardından EasyOCR GPU=True ile başlatılabilir.
Ama şu an kod `gpu=False` ile başlatıyor → değiştirmek istersen `plate_ocr.py` sat.62.

**Soru: "Plaka hiç okunmuyor (— gösteriyor)"**
Cevap: Bu normal — plaka tespiti yalnızca KRİTİK modda çalışır. Kameraya araç
yaklaştırınca QoD tetiklenmeli, ardından plaka okunmaya başlamalı. Ayrıca okunan
plakanın Türk formatı olması ve güven ≥ 0.70 gerekiyor.

---

## İlerisi İçin Hedefler

1. TOGG / komite verisini alınca `ai/training/` ile fine-tune yap
2. Plate bbox'ını daha iyi bul (şu an araç bbox'ından kestirme yapıyor)
3. Sürücü yorgunluk tespitini normal modda da dene (daha hafif model?)
4. `speed_calibration_k` sabitini gerçek saha ölçümüyle netleştir
5. Sigara ve kulaklık tespitini fine-tune sonrası aktif et

---

## Faydalı Kaynaklar

- [Ultralytics YOLOv8 Dökümantasyonu](https://docs.ultralytics.com/)
- [EasyOCR GitHub](https://github.com/JaidedAI/EasyOCR)
- [MediaPipe Face Mesh](https://google.github.io/mediapipe/solutions/face_mesh.html)
- [OpenCV Python Tutorials](https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html)
- Proje içi testler: `tests/test_pipeline_schema.py`, `tests/test_qod_trigger.py`
