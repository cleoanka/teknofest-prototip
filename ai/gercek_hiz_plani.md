# Gerçek (Metrik) Hız Tahmini Planı

**Kalibrasyonsuz Sabit Kameradan km/h: Oto-Kalibrasyon Stratejisi**

> TEKNOFEST 2026 · 5G & Yapay Zeka ile Akıllı Yol Güvenliği Yarışması (Turkcell)
> Aşama 2 · Sürüm 1.0 · 6 Haziran 2026
> Kapsam: `ai/speed.py` + `ai/tracking.py` — göreceli sezgiselden **metrik km/h**'ye geçiş
> Senaryo varsayımı: **sabit yol kenarı kamerası**, kamera parametreleri/konum **bilinmiyor**

---

## 1. Yönetici Özeti

Bugün `ai/speed.py` hızı **kalibrasyonsuz bir sezgiselle** üretiyor: bbox alan değişimi ile merkez kayışının normalize edilip `speed_calibration_k=900` gibi keyfi bir sabitle ölçeklenmesi. `ai/PROGRESS.md` (R5) bunu açıkça not ediyor: *"hız kalibrasyonsuz, gerçek km/h anlamlı değil — yalnızca ihlal eşiği için kullanılıyor."* Çıktı birim taşımıyor; bir aracın 60 mı 120 mi gittiğini söyleyemiyor, yalnızca "hareketin büyüklüğünü" sıralıyor.

Sorunun kökü tek bir eksik veri: **piksel → metre ölçeği (ppm)**. Sahnede 1 pikselin yerde kaç metreye karşılık geldiğini bilmeden hiçbir görüntü tabanlı yöntem metrik hız üretemez. Yarışma bize sabit kameralı bir video verecek ama kamera yüksekliği, açısı, odak uzaklığı veya sahnedeki bilinen mesafeleri **vermeyecek**. Dolayısıyla ölçeği **dışarıdan alamayız; sahnenin kendisinden türetmeliyiz.** Buna oto-kalibrasyon (self-calibration) denir.

Bu plan üç bağımsız oto-kalibrasyon kaynağı tanımlar, bunları bir füzyon katmanında birleştirir ve ground-truth olmadan nasıl doğrulanacağını anlatır:

- **A — Referans nesne boyutu (birincil):** Türk plakası **520 mm** ve sınıf-bazlı tipik araç genişliği (otomobil ~1.8 m, kamyon ~2.5 m) bilinen fiziksel ölçülerdir. Bunları zaten tespit ediyoruz; her karede yerel ppm'i bunlardan okuruz.
- **B — Şerit/yol işareti homografisi (ikincil, en sağlam):** TR standardı şerit genişliği (3.50–3.75 m) ve kesik çizgi adımı (otoyolda 4.5 m dolu + 7.5 m boş = **12 m**) bilinen yer düzlemi ölçüleridir. Bunlardan tam bir homografi (kuş bakışı dönüşüm) kurulur.
- **C — Kaçış noktası (vanishing point) self-kalibrasyon (referans/doğrulama):** Şerit çizgileri ve araç hareket yönünden kaçış noktası bulunarak kamera odak/poz parametreleri ve dolayısıyla ölçek geri kazanılır (literatürde standart yöntem).

Başarı kriteri yarışma puanlamasındaki YZ doğruluk ağırlığıdır; hedef metrik hızda **ortalama mutlak hata (MAE) ≤ ~%10–15**, ihlal (overspeed) tetikleme kararında ise **yüksek isabet**tir. İhlal eşiği `overspeed=15` ayar değeriyle birlikte gerçek km/h üzerinden anlam kazanır.

---

## 2. Mevcut Durumun Analizi

### 2.1 Bugünkü `speed.py` ne yapıyor?

```
speed_kmh = K * max(|Δalan_norm|^exp, |Δmerkez_norm|) * (fps/30)
```

İki bileşen var: alan değişimi (baş-on yaklaşmada bbox büyür) ve merkez kayışı (yanal/boyuna hareket). `max(...)` ile baş-on yaklaşmadaki "0 km/h" hatası çözülmüş. Bu **fikir olarak doğru** ama iki temel kusuru var:

1. **Birimsiz.** `K=900` keyfi; çarpan değişince "hız" değişir, gerçek dünyaya bağlı değil.
2. **Perspektif kör.** Kameradan uzaktaki bir araç, yakındaki araçla aynı gerçek hızda gitse bile çok daha az piksel oynar. Tek sahnede ppm konuma göre 3–5 kat değişir; tek `K` bunu yakalayamaz.

### 2.2 Elimizdeki yapı taşları (yeniden kullanılacak)

- `ai/tracking.py` → `IOUTracker` araçlara kalıcı `track_id` veriyor; `Track.center_history` ve `area_history` (maxlen=12) tutuyor. **Metrik hız için merkez geçmişini yer koordinatına çevirmemiz yeterli.**
- `ai/schema.py` → `Vehicle.bbox`, `Vehicle.plate_bbox`, `Vehicle.speed_kmh` alanları zaten var. Plaka kutusunu boyut referansı olarak kullanabiliriz.
- `ai/plate_ocr.py` / `lp_detector` → plaka tespiti mevcut; plaka piksel genişliği bedava ölçek sinyali.
- `config/settings.py` → `speed_calibration_k`, `speed_ppm_exponent`, `overspeed=15` ayarları mevcut; yeni parametreler buraya eklenir.

### 2.3 Tasarım ilkesi

> Tek bir global `K` yerine, **sahneye özgü ve konuma bağlı bir ölçek alanı** kuracağız. Hız her zaman **yer düzlemindeki metrik yer değiştirme / zaman** olarak hesaplanacak, piksel uzayında değil.

---

## 3. Temel Denklem ve Zaman Ekseni

Herhangi bir yöntem için iskelet aynıdır:

```
v (m/s) = Δs_metre / Δt_saniye
v (km/h) = v (m/s) * 3.6
```

- **Δs_metre:** Aracın iki kare arasında yer düzleminde aldığı gerçek mesafe (ölçek/homografi ile pikselden çevrilir).
- **Δt_saniye:** İki kare arasındaki süre. **Bu kritik ve sık atlanır.**

### 3.1 Zaman ekseninin güvenilirliği (ön koşul)

Δt yanlışsa hız yanlıştır — ölçek mükemmel olsa bile. Plan:

- Video nominal FPS'i (ör. 30) yerine **gerçek kare zaman damgalarını** kullan. `pipeline` zaten `client_ts`/`total_latency_ms` işliyor; varsa kare PTS'i (presentation timestamp) tercih et.
- Değişken FPS (VFR) videolarda `dt = t[i] - t[i-1]`'i kare başına ölç; sabit `1/fps` varsayma.
- Düşürülen kareler (dropped frames) için `track`'te son güncelleme zamanını sakla; `Δt`'yi geçen kare sayısıyla değil **gerçek geçen süreyle** hesapla.

---

## 4. Yöntem A — Referans Nesne Boyutu ile Oto-Kalibrasyon (Birincil)

**Fikir:** Sahnede fiziksel boyutu bilinen bir nesne varsa, o nesnenin piksel boyutu o derinlikteki yerel ppm'i verir.

### 4.1 Plaka tabanlı ölçek (en kesin)

Türk Tip-1 plakası standardı **520 mm × 120 mm**'dir (11.07.1999 / 23752 RG). Plakayı zaten tespit ediyoruz.

```
ppm_yerel = plaka_piksel_genişliği / 0.520     # piksel / metre
```

Bu, plakanın bulunduğu derinlikteki anlık ölçektir. Aracın o karedeki yer değiştirmesini bu ölçekle metreye çeviririz.

- **Avantaj:** Tek, dünya çapında sabit, çok hassas bir referans (genişlik varyansı ~%1).
- **Kısıt:** Plaka yalnızca araç yeterince yakın ve arka/ön cepheden görünürken okunur; açıyla daralır (foreshortening). Bu yüzden plaka genişliğini ölçek için kullanırken **yükseklik/genişlik oranı 520/120 ≈ 4.33'e yakınsa** (yani plaka cepheye dik görünüyorsa) güven yüksek; oran saparsa o ölçümü düşür.

### 4.2 Araç genişliği tabanlı ölçek (yedek)

Plaka yokken sınıf-bazlı tipik genişlik kullanılır:

| Sınıf | Tipik genişlik (m) | Notlar |
|---|---|---|
| otomobil | 1.80 | en yaygın; varsayılan |
| minibüs/van | 2.00 | |
| kamyon/otobüs | 2.50 | ayna hariç |

```
ppm_yerel = araç_bbox_piksel_genişliği / tipik_genişlik(sınıf)
```

- **Avantaj:** Her araçta var; plakaya bağlı değil.
- **Kısıt:** Bireysel araç genişliği ±%15–20 oynar; bu yüzden A.2 **tekil ölçüm için gürültülü**dür. Bunu tek araçtan değil, **çok sayıda araçtan istatistiksel olarak** kullanmak çok daha sağlamdır (bkz. §4.3).

### 4.3 Anlık ölçümden sahne ölçek-alanına

Tek karelik ppm gürültülüdür. Bunun yerine **kalibrasyon birikimi** yaparız:

1. Onlarca aracın plaka/genişlik ölçümünü, görüntüdeki **dikey konumlarına (y)** göre topla. Sabit kamerada derinlik ≈ y koordinatının fonksiyonudur (ufka yakın = uzak = küçük ppm).
2. `ppm(y)` için bir eğri (lineer veya 2. derece) regresyonla uydur. Aykırı ölçümleri RANSAC/medyan ile at.
3. Artık herhangi bir araç için, bulunduğu y'ye göre `ppm(y)`'yi okuyup metrik hız hesapla — plaka o anda görünmese bile.

> Bu adım, "kalibrasyonsuz" senaryoyu birkaç saniyelik trafik akışıyla **kendi kendini kalibre eden** bir sisteme dönüştürür. Video başında bir ısınma (warm-up) penceresi yeterlidir.

---

## 5. Yöntem B — Şerit/Yol İşareti Homografisi (En Sağlam, İkincil)

**Fikir:** Yer düzlemindeki bilinen iki mesafe (şerit genişliği ve kesik çizgi adımı) ile görüntüden kuş bakışına tam bir **homografi (H)** kurulur. Bundan sonra her piksel doğrudan metrik yer koordinatına eşlenir.

### 5.1 Bilinen TR ölçüleri (referans)

- **Şerit genişliği:** 1. sınıf yol 3.60–3.75 m, 2. sınıf 3.50 m, min. 2.75 m. (varsayılan 3.50 m, gerekirse parametre)
- **Kesik çizgi adımı (bölünmüş/otoyol):** 4.5 m dolu + 7.5 m boş = **12.0 m** tam adım. Şehir içi (50 km/h): 3 m + 3 m = 6 m adım.

### 5.2 Homografi kurulumu

1. Şerit çizgilerini tespit et (Hough/segmentasyon ya da hazır şerit modeli). En az iki paralel şerit çizgisi → **yanal ölçek** (genişlik).
2. Aynı çizgideki ardışık kesik çizgi başlangıçları → **boyuna ölçek** (12 m adım).
3. Yer düzleminde dört nokta (iki şeridin iki kesik segmenti) ↔ bilinen metrik koordinatlar eşlenir → `cv2.getPerspectiveTransform` / `findHomography` ile **H** bulunur.
4. Aracın yer temas noktasını (bbox alt-orta pikseli) `H` ile yere izdüşür → metrik (X, Z). İki kare arasındaki metrik mesafe / Δt → hız.

- **Avantaj:** Perspektifi **tam** çözer; tüm sahnede tutarlı metrik. Aracın derinliğinden bağımsız.
- **Kısıt:** Net şerit çizgisi gerektirir (gece/yağmur/aşınmış çizgide zorlaşır). Çizgi yoksa Yöntem A'ya düş.

---

## 6. Yöntem C — Kaçış Noktası ile Kamera Self-Kalibrasyonu (Doğrulama/Referans)

**Fikir:** Trafik sahnesinde iki diküm kaçış noktası bulunabilir: (VP1) yol yönündeki paralel çizgilerden, (VP2) araçların yanal kenarlarından. Bu iki VP'den kameranın odak uzaklığı ve duruşu, oradan da yer düzlemi ölçeği geri kazanılır (Dubská/Sochor tipi otomatik yol kamerası kalibrasyonu). Tek bir bilinen ölçü (şerit genişliği veya ortalama araç boyu) mutlak ölçeği sabitler.

- **Rol:** Üretimde zorunlu değil; A ve B'yi **bağımsız bir üçüncü yöntemle çapraz doğrulamak** ve ground-truth yokluğunda güven üretmek için. Üç yöntem birbirine yakınsa metrik hıza güveniriz.

---

## 7. Füzyon ve `speed.py` Yeniden Tasarımı

### 7.1 Karar mantığı (öncelik sırası)

```
1. Şerit homografisi (B) güvenilir kurulduysa  → birincil ölçek kaynağı
2. Değilse, plaka/araç ölçek-alanı ppm(y) (A) → ölçek kaynağı
3. İkisi de yoksa                              → "hız belirsiz" döndür (uydurma yapma)
```

### 7.2 Track düzeyinde hesap

- `Track`'e metrik yer-noktası geçmişi ekle: her güncellemede bbox alt-orta pikselini H veya ppm(y) ile yere çevir, `world_history`'ye yaz.
- Hızı **tek kare farkıyla değil**, kısa bir pencere üzerinden hesapla (ör. son 5–8 kare doğrusal uyum / medyan), jitteri bastır.
- **Aykırı reddi:** Fiziksel olmayan ivmeleri (ör. >8 m/s²) ve ppm güveni düşük kareleri at.
- **Düzgünleştirme:** Üstel hareketli ortalama (EMA) veya Kalman (sabit hız modeli) ile track başına hızı stabilize et.

### 7.3 Yeni ayar parametreleri (`config/settings.py`)

```python
plate_width_m = 0.520            # TR Tip-1 plaka standardı
vehicle_width_m = {"car":1.80,"van":2.00,"truck":2.50,"bus":2.50}
lane_width_m = 3.50              # varsayılan; saha/gizli sete göre override
dash_pitch_m = 12.0             # otoyol kesik çizgi adımı (4.5+7.5)
speed_window_frames = 6          # hız regresyon penceresi
speed_max_accel_mps2 = 8.0       # aykırı reddi eşiği
calib_warmup_frames = 90         # ppm(y) ısınma penceresi
# overspeed = 15  (mevcut) — artık gerçek km/h üzerinden anlamlı
```

### 7.4 Geriye uyum

- `speed_calibration_k` ve `speed_ppm_exponent` **fallback** olarak kalır: hiçbir oto-kalibrasyon kaynağı yoksa eski sezgisel "göreceli hız" modunda çalışır ama çıktı `is_calibrated=False` bayrağıyla işaretlenir, böylece raporlamada gerçek km/h ile karışmaz.

---

## 8. Doğrulama — Ground-Truth Olmadan Nasıl Güveniriz?

Elimizde etiketli gerçek hız yok. Üç katmanlı doğrulama:

### 8.1 Sentetik kontrollü test (kesin doğrulama)

Bilinen ppm ve bilinen FPS ile, bir kutuyu **bilinen piksel/kare hızında** hareket ettiren sentetik video/dizi üret. Beklenen km/h analitik olarak bilinir. Hattı bu girdiyle koştur, MAE ölç. **Bu, formül ve birim doğruluğunu %100 kanıtlar** (kamera/sahne belirsizliği olmadan).

### 8.2 Çapraz yöntem tutarlılığı

Aynı gerçek video klibinde A (plaka/araç), B (şerit homografisi), C (VP) bağımsız hız üretir. Üçü birbirine ≤ %10 yakınsa metrik hıza güven yüksektir. Sapma, hangi yöntemin bozulduğunu (ör. silik şerit → B düşer) gösterir.

### 8.3 Fiziksel akıl sağlığı kontrolleri

- Hızlar yol tipi sınırına makul aralıkta mı (şehir içi 0–90, otoyol 0–150)?
- Aynı track'te kareler arası ivme fiziksel mi?
- Bilinen referansla mini saha testi: bir aracı bilinen GPS hızında / bilinen iki nokta arası bilinen sürede geçirip kıyasla (mümkünse).

### 8.4 Raporlanacak metrikler

`eval/` altına bir `speed_eval` betiği: MAE (km/h), MAPE (%), ihlal kararı için precision/recall (overspeed eşiğinde), yöntemler-arası uyum (Bland–Altman). Sonuç `eval_perclass.log` tarzı bir loga yazılır.

---

## 9. Uygulama Yol Haritası (Aşamalı)

| Aşama | İş | Çıktı | Bağımlılık |
|---|---|---|---|
| 0 | Zaman ekseni: gerçek `dt`/PTS kullanımı | Güvenilir Δt | — |
| 1 | Yöntem A.1 plaka ppm + ppm(y) ölçek-alanı | Metrik hız (plaka görünürken) | plate_bbox |
| 2 | Yöntem A.2 araç-genişliği yedeği + füzyon | Plaka olmadan da hız | sınıf bilgisi |
| 3 | Track düzeyi pencere + Kalman/EMA + aykırı reddi | Stabil km/h | tracking.py |
| 4 | Yöntem B şerit homografisi | Perspektif-tam metrik | şerit tespiti |
| 5 | Sentetik + çapraz doğrulama + `speed_eval` | MAE/precision raporu | eval/ |
| 6 | Yöntem C (VP) — opsiyonel üçüncü doğrulama | Bağımsız teyit | — |

Aşama 0–3 tek başına kullanılabilir metrik hız verir ve gizli test setinde çalışır; 4–6 sağlamlık ve kanıt katmanıdır.

---

## 10. Riskler ve Önlemler

| Risk | Etki | Önlem |
|---|---|---|
| FPS/zaman damgası yanlış | Hız doğrudan ölçeklenir yanlış | Aşama 0; PTS doğrula; sentetik testle birim teyidi |
| Gece/yağmur → şerit/plaka görünmez | B ve A.1 düşer | A.2 araç-genişliği yedeği; `is_calibrated` bayrağı |
| Perspektif (tek K kör) | Uzak araçlar yavaş görünür | ppm(y) ölçek-alanı veya homografi |
| Gizli sette farklı çözünürlük/şerit ölçüsü | Sabitler kaymış | Parametreleştir (`lane_width_m`, `dash_pitch_m`); oto-kalibrasyon ölçeği veriden öğrenir |
| Tekil araç genişlik varyansı | A.2 gürültülü | Çok-araç istatistik + RANSAC, tek ölçüm değil |
| Ground-truth yok | Doğruluğu kanıtlayamama | §8 sentetik + çapraz yöntem + akıl sağlığı |

---

## 11. Özet Karar

Sabit kamera + sıfır kalibrasyon senaryosunda gerçek km/h **mümkündür**, ama dışarıdan ölçek beklemeden **sahneden oto-kalibrasyon** şarttır. Birincil olarak Türk plakası (520 mm) ve araç genişliğiyle bir `ppm(y)` ölçek-alanı kurulur (Aşama 1–3); mümkün olduğunda şerit homografisi (3.50 m genişlik, 12 m kesik çizgi adımı) perspektifi tam çözer (Aşama 4); kaçış noktası self-kalibrasyon bağımsız doğrulama sağlar (Aşama 6). Tüm yöntemler ortak metrik denklemde (`Δs_metre/Δt`) buluşur ve ground-truth olmadan sentetik + çapraz-yöntem + fiziksel kontrollerle doğrulanır. Eski sezgisel, hiçbir kaynak yoksa `is_calibrated=False` ile yedek kalır.

---

### Kaynaklar

- Türk plaka standardı (Tip-1 520×120 mm): [OTORAF — Standart Plaka Ölçüleri](https://www.otoraf.com/standart-plaka-olculeri-nelerdir.html), [TSOF](https://www.tsof.org.tr/2016/039.pdf)
- Şerit genişliği ve kesik çizgi standartları: [KGM Karayolu Trafik İşaretleme Standartları](https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Trafik/IsaretlerElKitabi/KarayoluTrafikIsaretlemeStandartlari1.pdf), [Otoyol şerit genişliği](https://enpopulersorular.com/library/lecture/read/239947-otoyollarda-serit-genisligi-kac-metredir)
- Mevcut kod referansları: `ai/speed.py`, `ai/tracking.py`, `ai/PROGRESS.md` (R5), `config/settings.py`
