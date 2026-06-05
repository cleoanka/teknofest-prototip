# Model Eğitim Planı

**Sıfır Etiketten Sahaya: Açık Kaynak Veriyle Geniş Ölçekli Eğitim Stratejisi**

> TEKNOFEST 2026 · 5G & Yapay Zeka ile Akıllı Yol Güvenliği Yarışması (Turkcell)
> Yapay Zeka Çıkarım Hattı — Aşama 2 · Sürüm 1.0 · 5 Haziran 2026
> Kapsam: `ai/` kolu — detektör eğitimi, veri stratejisi, donanım yol haritası

---

## 1. Yönetici Özeti

Bu belge, projede kullanılacak YZ modelinin **nasıl, ne ile ve nerede** eğitileceğini uçtan uca tarif eder. Mevcut prototip COCO ön-eğitimli YOLOv8 ve MOCK mod ile çalışmaktadır; elimizde henüz eğitilmiş özel model ve etiketli saha verisi yoktur. Hedefimiz, gizli test setinin farklı araç, açı ve hava koşulları içereceği gerçeğini gözeterek **genelleyen, tek ve geniş bir çok-sınıflı detektör** eğitmektir.

Stratejinin üç dayanağı:

- **Veri (Ne ile?):** Sıfır etiketle başlıyoruz; büyük açık kaynak veri setlerinden (COCO, BDD100K, CCPD, sürücü davranışı setleri) sınıf bazında havuz kurup tek bir birleşik kümeye normalize ediyoruz.
- **Yöntem (Nasıl?):** Transfer öğrenme ile COCO ağırlıklarından başlayıp aşamalı (kolay→zor) müfredat ve agresif augmentation ile fine-tune ediyoruz. Normal mod için `yolov8n`, kritik mod için `yolov8s/m`.
- **Donanım (Nerede?):** Önce yerel RTX 4060 üzerinde küçük ölçekte doğrulama; ardından geniş eğitim için saatlik kiralık bulut GPU (RTX 4090 / A100). Tek tam eğitim turu tahmini **5–25 USD**.

Başarı, eğitim metriklerinden (mAP) çok, TEKNOFEST puanlama tablosundaki **%40 ağırlıklı "YZ analizi doğruluk/hassasiyet"** kriterine ve QoD tetiklemesinin Normal→Kritik doğruluk farkını kanıtlamasına bağlanmıştır.

---

## 2. Mevcut Durum ve Hedef

### 2.1 Bugün elimizde ne var?

- Uçtan uca çalışan YZ hattı: `detector`, `tracking`, `speed`, `plate_ocr`, `driver_state`, `risk`, `qod_trigger`, `pipeline` modülleri hazır.
- Detektör şu an COCO ön-eğitimli YOLOv8 ile çalışıyor; kütüphane yoksa sistem otomatik **MOCK** moduna düşüyor.
- `ai/training/` altında eğitim iskeleti hazır: `data.yaml` (7 sınıf), `train.py` (fine-tune + augmentation + INT8 export), `prepare_dataset.py`.

### 2.2 Eksik olan ne?

- Eğitilmiş özel model yok (yalnızca COCO/MOCK).
- Etiketli saha verisi yok; komite/TOGG seti henüz paylaşılmadı.
- Saha hız kalibrasyonu ve Windows/CUDA üzerinde doğrulanmış çalıştırma bekliyor.

### 2.3 Hedef

Tek ağırlık dosyasıyla 7 sınıfı (`vehicle, license_plate, person, phone, cigarette, seatbelt, headphone`) tespit eden, gece/yağmur/farklı açılarda genelleyen, gerçek zamanlı (Normal modda **>25 FPS**) çalışan bir detektör üretmek. Komite verisi geldiğinde yalnızca son bir fine-tune turu ile saha verisine uyarlanabilir olmalı.

---

## 3. Ne Eğiteceğiz? — Model Mimarisi ve Sınıflar

"Geniş model" ifadesini iki katmanda ele alıyoruz: (a) geniş veri ile eğitilmiş ama gerçek zamanlı kalan tek bir detektör; (b) ağır modda daha büyük omurga. Tek dev model yerine, QoD mimarisine uygun **iki-kademeli detektör** eğitiyoruz:

| Kademe | Omurga | Görev | Hedef hız |
|---|---|---|---|
| Normal mod | YOLOv8n (nano) | Sadece araç varlığı + bbox büyümesi + güven; düşük bant, yüksek FPS | ~25-40 FPS (4060) |
| Kritik mod | YOLOv8s veya m | 7 sınıfın tamamı: plaka, telefon, sigara, kemer, kulaklık, kişi | ~12-25 FPS (4060) |

Detektör (YOLOv8) yalnızca "nesneleri kutula" görevini üstlenir. **Plaka okuma (OCR)**, **yorgunluk (MediaPipe EAR/PERCLOS)** ve **hız tahmini** bu modelin üzerine binen ayrı modüllerdir ve ağır eğitim gerektirmez. Yani eğitim eforumuzun **~%90'ı tek bir YOLO detektörüne** odaklanır.

### 3.1 Neden tek birleşik detektör?

- Tek geçişte tüm sınıflar → düşük gecikme (her sınıf için ayrı model çalıştırmaktan hızlı).
- QoD mimarisiyle uyumlu: hafif/ağır model takası tek bir aile içinde (n→s→m) kolay.
- Bakım kolaylığı: sınıf eklemek = `data.yaml` + `config/settings.py` güncellemesi.

---

## 4. Nereden Veri? — Sıfır Etiketten Büyük Açık Kaynak Havuzuna

Etiketimiz olmadığı için strateji nettir: her sınıf için halka açık, lisansı uygun ve büyük veri setlerinden alt küme çekip tek bir **YOLO formatlı birleşik kümeye** normalize ederiz.

| Sınıf | Başlıca kaynak(lar) | Büyüklük / not | Lisans |
|---|---|---|---|
| vehicle | COCO (car/truck/bus) + BDD100K | ~110K görüntü (BDD) sürüş sahnesi; gündüz/gece/yağmur | BSD-3 / CC |
| person | COCO + BDD100K (pedestrian) | Geniş; yaya ve sürücü gövdesi | BSD-3 / CC |
| license_plate | CCPD (2019/2020) + Roboflow TR-plaka | CCPD ~300K+ plaka; bulanık/eğik/yağmur çeşitliliği | Akademik / Roboflow |
| phone | State Farm Distracted Driver + Roboflow | Sürücü elinde telefon sahneleri | Kaggle/Roboflow |
| cigarette | Roboflow smoking setleri + kendi etiketleme | Küçük; augmentation ile çoğaltılır | Roboflow |
| seatbelt | Roboflow seatbelt + araç içi setler | Orta; takılı/değil dengesi önemli | Roboflow |
| headphone | Açık kaynak az → küçük özel etiketleme | Nadir sınıf; sentetik çeşitleme şart | Karma |

**Önemli not — lisans ve genelleme:** CCPD ağırlıklı olarak Çin plakalarını içerir; plaka tespiti (kutu) için iyi genelleşir ama OCR'ın Türk plaka biçimine uyarlanması için Roboflow TR-plaka setleri ve birkaç yüz kendi etiketimiz eklenmelidir. Her setin lisansını yarışma kullanımı için ayrıca teyit ediyoruz.

### 4.1 "Çok büyük veri" ne kadar büyük olmalı?

| Sınıf grubu | Hedef örnek (kutu) | Yöntem |
|---|---|---|
| Bol sınıflar (vehicle, person) | 20K – 60K kutu | Açık kaynaktan bolca; alt-örnekleme gerekebilir |
| Orta sınıflar (plaka, phone, seatbelt) | 3K – 10K kutu | Açık kaynak + sınırlı kendi etiketleme |
| Nadir sınıflar (cigarette, headphone) | 800 – 3K kutu | Augmentation + kopya-yapıştır artırımı şart |

Sınıf dengesizliği gerçek bir risktir: `vehicle` on binlerce, `headphone` birkaç yüz olabilir. Bunu (i) `cls` kayıp ağırlığı, (ii) nadir sınıfa kopya-yapıştır augmentation, (iii) bol sınıfta alt-örnekleme ile dengeleriz.

---

## 5. Veri Hazırlama Hattı

1. **Toplama:** Her kaynaktan ilgili sınıfları indir/süz; YOLO formatına (`class x y w h`, 0-1 normalize) çevir.
2. **Normalize:** Sınıf kimliklerini tek şemaya eşle (COCO car/truck/bus → `vehicle=0`). `data.yaml` sınıfları `config/settings.py:TARGET_CLASSES` ile birebir aynı kalmalı.
3. **Etiketleme:** Eksik sınıflar (cigarette/headphone) için Roboflow/CVAT/labelImg ile birkaç yüz kare etiketle. Komite videosu gelince `prepare_dataset.py frames` ile kare çıkar.
4. **Tekilleştirme:** Çift/benzer kareleri ele (ardışık video kareleri) — veri sızıntısını önlemek için.
5. **Bölme:** 70/15/15 video/kaynak-bazlı böl. Aynı videonun kareleri tek bölmede kalmalı.
6. **Doğrulama:** Birleşik kümeyi `datasets/yolguvenligi/` altına yerleştir; etiket kutularını gözle doğrula.

```bash
python -m ai.training.prepare_dataset scaffold --root datasets/yolguvenligi
python -m ai.training.prepare_dataset frames --video ornek.mp4 --out datasets/raw --fps 2
```

---

## 6. Nasıl Eğiteceğiz? — Eğitim Metodolojisi

### 6.1 Transfer öğrenme + aşamalı müfredat

1. **Adım 1** – COCO ön-eğitimli `yolov8s.pt` ağırlıklarından başla (sıfırdan eğitmek hem yavaş hem veri-aç).
2. **Adım 2** – Önce bol/kolay sınıflarla (vehicle, person) kısa bir tur; omurga sürüş alanına ısınır.
3. **Adım 3** – Tüm 7 sınıfı içeren birleşik kümeyle ana fine-tune (80 epoch, erken durdurma `patience=20`).
4. **Adım 4** – Komite/TOGG verisi gelince düşük öğrenme oranıyla kısa bir saha-uyarlama turu.

### 6.2 Augmentation (genelleme için zorunlu)

Gizli test farklı araç/açı/hava içereceği için agresif veri artırımı uyguluyoruz: mozaik (1.0), mixup (0.1), HSV renk jitter (h .015 / s .7 / v .4), döndürme (5°), öteleme (0.1), ölçek (0.5), yatay çevirme (0.5). Gece/yağmur için ek sentetik karartma ve yağmur damlası artırımı önerilir.

### 6.3 Başlangıç hiperparametreleri

| Parametre | Değer | Gerekçe |
|---|---|---|
| base | `yolov8s.pt` | COCO ön-eğitimli; nano için `yolov8n.pt` |
| epochs | 80 (patience 20) | Erken durdurma ile aşırı öğrenmeyi engelle |
| imgsz | 640 | Plaka için 960 denemeye değer (küçük nesne) |
| batch | 16 (4060) / 32–64 (bulut) | VRAM'a göre; OOM olursa düşür |
| device | auto (cuda/mps/cpu) | 4060'da cuda; Mac'te mps |
| cls | 0.7 | Nadir sınıf için sınıf kaybını artır (focal etkisi) |
| lr (saha turu) | düşük (~0.001) | İnce ayarda katastrofik unutmayı önler |

```bash
python -m ai.training.train --data ai/training/data.yaml --base yolov8s.pt \
    --epochs 80 --imgsz 640 --batch 16 --device auto --export-int8
```

---

## 7. Nerede Eğiteceğiz? — Donanım Yol Haritası

İki fazlı ilerliyoruz: önce yerel PC'de (RTX 4060) küçük ölçekte doğrula, sonra geniş eğitimi saatlik kiralık bulut GPU'ya taşı. İleride yoğun kullanım olursa özel iş istasyonu (RTX 4090/5090) satın alımı değerlendirilir.

| Faz | Donanım | Maliyet | Ne için | Not |
|---|---|---|---|---|
| Faz A — Yerel doğrulama | RTX 4060 (8GB) | Ücretsiz (mevcut) | Hat doğrulama, küçük alt-küme, hiperparametre | VRAM 8GB → batch 8–16 |
| Faz B — Geniş eğitim | RTX 4090 (kiralık) | ~0.31–0.34 USD/sa | Tam birleşik kümeyle 80 epoch ana tur | Tek tur 3–8 saat |
| Faz B+ — Çok büyük | A100 80GB (kiralık) | ~0.67–1.89 USD/sa | Çok büyük küme / yüksek imgsz / m-l omurga | 80GB → büyük batch |
| Faz C — Kalıcı (ops.) | RTX 4090/5090 iş ist. | Tek seferlik donanım | Sık eğitim + saha demo + canlı çıkarım | Yarış sonrası süreklilik |

### 7.1 Bulut sağlayıcı seçenekleri (Haziran 2026 güncel)

| Sağlayıcı | Yaklaşık USD/saat | Not |
|---|---|---|
| RunPod (Community) | RTX 4090 ~0.34 / A100 80GB ~0.89 | Kolay arayüz, saniye-bazlı ücret, hazır PyTorch imajları |
| Vast.ai (pazar yeri) | RTX 4090 ~0.31 / A100 80GB ~0.67 | En ucuz; fiyat arz-talep ile değişir, dağıtımda canlı teyit et |
| Lambda / diğerleri | Değişken | Kurumsal; uzun süreli kiralamada değerlendirilir |

Fiyatlar gerçek zamanlı pazar ile değiştiği için dağıtım anında canlı listeden teyit edilmelidir (özellikle Vast.ai). Tahmini tek tam eğitim turu maliyeti: 4090'da 3–8 saat × ~0.33 USD ≈ 1–3 USD; birkaç deneme turuyla toplam genelde **5–25 USD** aralığında kalır.

### 7.2 Pratik kural

- Veri hazırlama, kod denemesi ve küçük testleri **yerelde (4060)** yap — bulut saati boşa gitmesin.
- Yalnızca tam/geniş eğitim turunda bulut GPU kirala; bittiğinde örneği **hemen kapat**.
- Veri ve ağırlıkları kalıcı diske/kovaya yedekle; spot/kesintili örneklerde checkpoint kullan.
- Ücretsiz alternatif: **Kaggle** (haftalık ~30 saat T4×2) ilk denemeler için bedava bir basamak.

---

## 8. Değerlendirme ve Başarı Kriterleri

Eğitim başarısını yarışma puanlamasına bağlıyoruz. Sadece mAP değil, TEKNOFEST Tablo-1 kriterleriyle eşleşen ölçütler raporlanır.

| Eksen | Metrik | Nasıl ölçülür |
|---|---|---|
| Genel doğruluk | mAP@50 ve mAP@50-95 (test bölmesi) | `split=test` ile `model.val()` |
| Sınıf bazında | Her sınıf için precision/recall, özellikle nadir sınıflar | Karışıklık matrisi + PR eğrileri |
| YZ doğruluk (%40) | Araç/plaka/hız/araç içi nesne doğruluğu | `eval/evaluate.py` Normal vs Kritik |
| QoD kanıtı (%40) | Kritik modun Normal'e göre doğruluk artışı + bant verimliliği | eval karşılaştırma raporu |
| Hız/gecikme | FPS (Normal>25), INT8 ile gecikme azalışı | Hedef donanımda ölçüm |

**Kabul eşiği (öneri):** vehicle/person mAP@50 ≥ 0.85; plaka tespiti ≥ 0.80; nadir sınıflar ≥ 0.60 (augmentation sonrası). Saha turundan sonra yeniden ölç.

---

## 9. Optimizasyon ve Devreye Alma

- **Nicemleme:** INT8/ONNX/TensorRT export ile ~%20–35 gecikme azalması, <1.5 mAP kaybı hedeflenir (`train.py --export-int8`).
- **Entegrasyon:** `runs/detect/yolguvenligi*/weights/best.pt` → `.env` içinde `YOLO_MODEL_CRITICAL` olarak ver; sistem otomatik bu ağırlığı kullanır.
- **İki kademe:** Normal modda `yolov8n`, kritik modda eğitilmiş `best.pt`; QoD tetikleyince ağır modele geçiş.
- **Güvenli geri düşüş:** `AI_MODE=auto` ile kütüphane varsa gerçek model, yoksa MOCK; testler her ortamda yeşil kalır.

---

## 10. Zaman Çizelgesi (Önerilen Fazlar)

| Faz | İş | Nerede | Süre (tahmini) |
|---|---|---|---|
| F1 | Açık kaynak setleri indir + YOLO formatına normalize et | Yerel | 2–4 gün |
| F2 | Nadir sınıfları etiketle (cigarette/headphone/seatbelt) | Yerel | 2–3 gün |
| F3 | 4060'da küçük alt-küme ile boru hattı doğrula | RTX 4060 | 1 gün |
| F4 | Bulutta tam birleşik kümeyle ana eğitim (80 epoch) | RTX 4090 | 1 gün (3–8 saat) |
| F5 | Değerlendir (mAP + eval Normal/Kritik), hata analizi | Yerel | 1–2 gün |
| F6 | INT8 export + sisteme entegre + saha demo | Yerel/4060 | 1 gün |
| F7 | Komite verisi gelince saha-uyarlama fine-tune | Bulut | Komiteye bağlı |

---

## 11. Riskler ve Önlemler

| Risk | Önlem |
|---|---|
| Sınıf dengesizliği (nadir sınıflar) | Augmentation kopya-yapıştır, cls ağırlığı, bol sınıfta alt-örnekleme |
| Veri sızıntısı (ardışık video kareleri) | Kaynak/video-bazlı bölme; tekilleştirme |
| Lisans uyumsuzluğu (akademik-sınırlı set) | Her set lisansını yarışma kullanımı için teyit; gerekirse yalnız eğitimde |
| Plaka OCR'ın TR'ye uymaması (CCPD Çin ağırlıklı) | TR-plaka seti + birkaç yüz kendi etiketi ile uyarlama |
| 8GB VRAM yetersizliği | Geniş eğitimi buluta taşı; yerelde batch/imgsz düşür |
| Tek videoya aşırı uyum | Genel çözüm ilkesi (K-004): asla tek senaryoya özel eğitim |
| Bulut maliyet kayması | Sadece tam turda kirala; bitince kapat; spot+checkpoint |

---

## 12. Hızlı Komut Özeti

```bash
# 1) İskelet + kareleme
python -m ai.training.prepare_dataset scaffold --root datasets/yolguvenligi
python -m ai.training.prepare_dataset frames --video ornek.mp4 --out datasets/raw --fps 2

# 2) Eğitim (bulut GPU önerilir)
pip install ultralytics
python -m ai.training.train --data ai/training/data.yaml --base yolov8s.pt \
    --epochs 80 --imgsz 640 --batch 16 --device auto --export-int8

# 3) Değerlendirme
python -m eval.evaluate

# 4) Devreye alma (.env)
YOLO_MODEL_CRITICAL=runs/detect/yolguvenligi/weights/best.pt
AI_MODE=auto
```

---

## Kaynaklar

- BDD100K — doc.bdd100k.com/download.html (BSD-3, ~110K sürüş görüntüsü)
- CCPD — github.com/detectRecog/CCPD (~300K+ plaka)
- COCO — cocodataset.org (vehicle/person/phone alt sınıfları)
- RunPod fiyatlandırma — runpod.io/pricing
- Vast.ai — vast.ai (pazar yeri, canlı fiyat)
- Roboflow Universe — universe.roboflow.com (plaka/sigara/kemer/telefon setleri)
- Ultralytics YOLOv8 — docs.ultralytics.com
