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

#### 4.1.1 Köşe-tabanlı PnP — foreshortening'i atmak yerine ÇÖZ (Katman 2, uygulandı 2026-06-07)

Yukarıdaki "oran saparsa düşür" kuralı eğik plakaları **veri olarak çöpe atıyor**; açılı yol kamerasında plakaların çoğu hafif eğik olduğundan çok ölçüm kaybedilir. Daha iyisi: açıyı bir hata gibi elemek yerine **bilinmeyen olarak çözmek.**

Plaka düz bir nesnedir ve **4 köşesini** zaten tespit ediyoruz (`plate_crop.perspective_correct()` → `plate_corners`). 4 nokta + bilinen fiziksel boyut (520×112 mm) + odak uzaklığı → **düzlemsel PnP** (Perspective-n-Point) plakanın kamera-uzayı pozunu doğrudan verir: derinlik `Z`, yaw, pitch.

```
ppm_yerel = focal_px / Z        # o derinlikteki görüntü-düzlemi ölçeği
```

Bu ppm **foreshortening'den bağımsızdır**: PnP açıyı (yaw/pitch) zaten çözdüğü için, plaka 35° eğik olsa bile `Z` doğru çıkar → ppm doğru. Naif `w_piksel/0.520` ise aynı durumda `cos(yaw)` kadar yanılır.

- **Yöntem:** Zhang düzlemsel homografi ayrıştırması — `H = K·[r1 r2 t]`, `K⁻¹H`'den R,t. **Saf numpy** (cv2 gerekmez; K4 mock-first).
- **Odak (`focal_px`):** Kalibre kamera yoksa yatay FOV varsayımından (`f=(W/2)/tan(HFOV/2)`, HFOV≈55°). **Bu varsayım ppm'i bozmaz:** `H` gözlenen plaka piksellerinden çözülür (odaktan bağımsız) ve `Z∝f` olduğundan `ppm=f/Z`'de focal **sadeleşir**. Deneyle (2026-06-07): true HFOV 45–65° bandında cepheden ppm hatası **%0**, yaw=40°'de ~%2-5 (bkz. `gercek_hiz_progress.md`). Yani **mutlak ölçek çapası focal değil, plakanın 520mm genişliğidir.** Önceki "VP-focal bağlanınca mutlak ölçek iyileşir" notu geçersizdir; VP'nin yeri §8.2 güven sinyalidir (§12-P5), ppm üreticisi değil.
- **Rol:** Yöntem A'yı **güçlendirir**, B'nin yerini almaz. Füzyon önceliği (§7.1) korunur; PnP yalnız ölçek-alanı (A) beslemesini açılı plakalarda da geçerli kılar. Pose makul değilse (reprojeksiyon yüksek / Z aralık dışı / tilt > 60°) eski `plate_ppm`'e düşülür.
- **Kanıt:** sentetik kamerayla 35° yaw'da naif genişlik %10+ yanılırken PnP %3 içinde (`tests/test_plate_pnp.py`, 13 test). Detay: `gercek_hiz_progress.md`.

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
| 2+ | **Köşe-tabanlı PnP** (§4.1.1) — foreshortening-bağımsız ppm | Açılı plakada da doğru ölçek | plate_corners |
| **7.1** | **Canlı akış Δt** (§12-P1) — kare-zaman damgası / monotonik sayaç | Ağ-jitter'dan bağımsız Δt | app.js, main.py |
| **7.2** | **Boyuna hız** (§12-P2) — PnP `dZ/dt` + yanal füzyon | Homografisiz boyuna undershoot'u giderir | plate_pnp Z |
| **7.3** | **Bağımsız-GT eval** (§12-P3) — pinhole'dan üret, oto-kalibre ile çöz | İlk dürüst MAE (%10-15 hedefi) | eval/ |
| **7.4** | **Anizotropik dash-pitch koruması** (§12-P4) — yön-içi `dv/dh` + hibrit | 2× boyuna şişmeyi yakalar/düzeltir | homografi |
| **7.5** | **§8.2 + `scale_confidence`** (§12-P5) — `methods_agree` bağla (additive) | Güven-farkındalı raporlama; VP'ye gerçek rol | VP, last_pose |
| **7.6** | **`run_focal_bias()`** (§12-P6) + PnP eval kolu | focal-bağışıklık regresyonu; PnP recall | eval/ |

Aşama 0–3 tek başına kullanılabilir metrik hız verir ve gizli test setinde çalışır; 4–6 sağlamlık ve kanıt katmanıdır. **Aşama 2+ (PnP, 2026-06-07 uygulandı)** Yöntem A'yı açılı plakalara genişletir. **Aşama 7.x (2026-06-07 denetimi)** bir sonraki sınırdır — gerçek doğruluğu (özellikle gizli test setinde) artıran, kod-temelli ve adversaryal-doğrulanmış işler; tam gerekçe §12'de.

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

## 12. Sonraki Sınır — Adversaryal Denetimden Doğrulanmış Geliştirmeler (2026-06-07)

Aşama 0–6 + PnP "uygulandı" durumda olduğundan bu bölüm bir sonraki sınırı tanımlar:
gerçek doğruluğu (özellikle **gizli test setinde**) artıran, **kodun belirli bir satırına
dayanan** ve 39-ajanlık bir adversaryal denetimle (32 aday → 9 doğrulanmış) sınanan işler.
ROI (etki/çaba) sırasıyla. Plan↔kod boşluklarının dürüst dökümü `gercek_hiz_progress.md`'de.

> **Uygulama durumu (2026-06-07 akşam):** P1–P6 + quick-win'ler **KODA DÖKÜLDÜ ve test
> edildi** (343→358 yeşil). Ne yapıldı + ne ÖLÇÜLDÜ ve dürüst nüanslar (P2'nin focal
> ödünleşmesi, PnP per-sample gürültüsü, P4'ün güvenli alt-kümesi) → `gercek_hiz_progress.md`.

### P1 — Canlı akış zaman ekseni: kare-zaman damgası + monotonik sayaç [high · small]
**Neden:** Proje başlığı "5G ile canlı". `frontend/app.js:111` ve `tools/camera_client.py:59`
yalnız `{frame}` gönderiyor — `client_ts` yok → `backend/main.py:1110` `client_ts=None` →
`pipeline.py:266` `vts=t0=time.time()` (wall-clock). Canlı akışta Δt = sunucuya **varış**
farkı; ağ jitter'ı/kuyruk/GC doğrudan `v=Δs/Δt`'ye girer. `Track.ts_history` ve
`_robust_speed_mps` paydası (`calibration.py:335`) bu bozuk damgayı kullanır.
**Ne:** (A) `app.js`/`camera_client` JSON'una `client_ts=Date.now()/1000` ekle (ağ varış
jitter'ını dışlar). (B) Asıl çözüm: `pipeline.process` imzasına `frame_index`; backend
canlı akışta monotonik kare sayacı tutsun; `frame_ts None` ise `vts = frame_index/fps`
(ağ+NTP'den bağımsız tek-tipli Δt); en kötü ihtimalle `time.monotonic()`. (C) sayaç ile
istemci `capture_ts`'i çapraz-kontrol, büyük tutarsızlıkta sayacı otorite kıl.
**Doğrulama:** `speed_noise_probe`'a Δt-jitter sütunu (şu an iz `ts=k*dt` temiz); enjekte
edilen sentetik jitter altında `frame_index` fallback'in MAE'yi düşürdüğünü göster.

### P2 — Boyuna hız: PnP derinlik-zaman (`dZ/dt`) + ppm(y) undershoot [high · medium]
**Neden:** Kameranın **fiziksel olarak en güçlü çözdüğü** büyüklük (derinlik Z,
`plate_pnp.py:165,180`) hıza **hiç bağlanmıyor** — `calibration.py:219`'da `last_pose`
tek skaler üzerine yazılıyor, Z atılıyor; `Track`'te Z-geçmişi yok. Homografisiz kolda
(gizli setin baskın rejimi) boyuna hareket ppm(y)'den zorla türetiliyor ve perspektif
sıkışmasından **sistematik düşük** çıkıyor (`speed_eval.py:184`: `est_ppm_long << true`).
**Ne:** `observe_plate_pose`'a `track_id`+`ts` geçir (pipeline'da `primary_track.track_id`
ve `vts` zaten mevcut); `track_id→deque[(ts,Z)]` (`_pnp_z_hist`) tut. `estimate()`'te
**homografi yokken** ve boyuna baskınken (yatay foot kayması küçük ∧ |ΔZ| büyük):
`v_radial=|Z[b]−Z[a]|/Δt` **uzun-baz-çizgisiyle**; `v_lateral`=yanal piksel × ppm(y);
`v=√(v_radial²+v_lateral²)`. **Kritik:** `dZ/dt` yalnız **radyal** bileşendir, toplam
hızın yerine koyma. Z örnekleri seyrek (PnP yalnız critical+4 köşe) → ≥2-3 poz, Δt>0.2s,
reproj/tilt kapıları örnek almadan önce; |ΔZ| mutlak (yaklaşanda Z azalır).
**Doğrulama + ÖLÇÜLDÜ (uygulandı):** bağımsız pinhole-GT'de boyuna **MAE 0.0** (yalnız-ppm
yolu 68.7 / MAPE %95.5 undershoot). **ÖDÜNLEŞME (uygulamada öğrenildi):** `ppm=focal/Z`'de
`Z∝f` olduğundan `dZ/dt` **focal-oranı kadar yanlıdır** (HFOV ±10° → hız ∓~%10; ölçülen
45°→−%20, 65°→+%22) — ppm yolunun aksine (o focal-robust ama undershoot eder). Net: füzyon
undershoot'tan (~%95) çok daha iyi; ama focal'ı VP'den kalibre etmek **artık daha değerli**
(P6/§E). Ayrıca per-frame PnP Z gürültülü (§D ~%20); uzun-baz + Kalman + çok-örnek bunu bastırır.

### P3 — Bağımsız-GT eval: pinhole'dan üret, oto-kalibrasyonla çöz [high · small]
**Neden:** `speed_eval.py:135-136` izi `g2i`'den üretip aynı `i2g`'yi `set_homography` ile
veriyor → `MAE~0` **kaçınılmaz** (yalnız cebir/birim kanıtı; `speed_noise_probe.py:4-6` bunu
itiraf ediyor). Oto-kalibrasyonun (`observe→maybe_fit→estimate→km/h`) **gerçek** doğruluğu
hiç ölçülmedi; §1'deki **%10-15 hedefiyle kıyaslanabilir ilk dürüst rakam** bu olur.
**Ne:** `eval/`'a bağımsız-GT kolu ekle (`tests/test_plate_pnp.py:_project` pinhole'unu
yeniden kullan, `GroundHomography`'ye **dokunma**). İki AYRI kol: **(A) PnP kolu** — GT
köşelerini `f_gt` ile üret ama estimator'a verme (`camera_focal_px=None`); uçtan-uca
estimate() MAE. **(B) Genişlik kolu** — `observe_vehicle/plate_ppm` ile kalibre, GT yine
pinhole → rezidü "lineer ppm(y) vs pinhole 1/Z" model-uyumsuzluğunu yakalar. İki MAE'yi
ayrı raporla, focal-bias ile model-uyumsuzluğunu **karıştırma**.
**Doğrulama:** `camera_focal_px` verilince A-kolu MAE'sinin ~0'a inmesini de göster.

### P4 — Ölçek-çakışma kontrolünü yöne duyarlı yap + hibrit düzeltme [high · small]
**Neden:** `_local_ppm_homography` (`calibration.py:285`) izotropik ortalama
`0.5*(dh+dv)` üretiyor. Yanlış `dash_pitch` (şehir içi 6 m'yi otoyol 12 m sanmak) **yalnız
boyuna (dv)** ekseni 2× şişirir, yanal (dh) doğru kalır → birleşik oran ~1.5 < eşik 1.8 →
guard **tetiklenmiyor**, boyuna hız ~2× şişik kalıyor (`speed_noise_probe.py:77-106` bunu
belgeliyor). `test_calibration.py:262-280` yalnız izotropik 2.5× test ediyor.
**Ne:** Yön-içi self-tutarlılık: `dv` tabanlı boyuna ppm'i homografinin **kendi**
`dh` tabanlı yanal ppm'iyle kıyasla (yanlış pitch'te `dv/dh=2.0`, doğruda ~1.11 perspektif
anizotropisi); eşiği bu tabana göre ~1.4-1.5'e indir. **Hibrit (homografiyi atmadan düzelt):**
`use_h=False` ile homografiyi tamamen bırakmak yerine boyuna ekseni plaka çapasıyla
geri-çöz: `k_long = median(Z_homog / pose.distance_m)` (her ikisi de gerçek-Z; testte tam
2.0000 verdi), `_step_meters` homografi dalında **yalnız** Z bileşenini `/k_long` ölçekle,
yanal (X) dokunma. Böylece perspektif-tam yanal ölçek korunur. Yalnız `homography_auto`/
manuel-H açıkken etkili (varsayılan kapalı).
**Doğrulama:** `test_calibration.py`'ye anizotropik vaka (plaka anchor doğru, homografi 2×
pitch) → guard `True` dönmeli; hibrit kolda boyuna hız true'ya dönmeli.

### P5 — §8.2 çapraz-doğrulama + `scale_confidence` (additive) [medium · medium]
**Neden:** `estimate()` ikili `(km/h, True)` döndürüyor — **güven derecesi yok**.
`methods_agree`/`confidence_from_agreement` (`vanishing_point.py`) **var ama hiç
kullanılmıyor**; `last_pose` saklanıyor ama okunmuyor. Ground-truth yokken bağımsız
yöntemlerin **yakınsaması** doğruluğa dair en güçlü sinyaldir. Bu, Aşama 6/VP'ye nihayet
gerçek bir **üretim rolü** verir (şu an pipeline'a bağlı değil — bkz. progress).
**Ne:** (1) Boolean'ı **ezme** (düşük güvende `is_calibrated=False` yapmak sezgisele
düşürür → doğruluğu **düşürür**); `schema.Vehicle`'a **additif** `scale_confidence:
Optional[float]` ekle, metrik hızı her zaman raporla. (2) Uyumu **cv2-bağımsız**,
varsayılanda mevcut kaynaklardan üret: aynı y civarında PnP-ppm vs `plate_ppm` vs araç-
genişliği ppm medyanlarının yayılımı → `confidence_from_agreement`. (3) Homografi açıksa
ikinci kol olarak `_local_ppm_homography`. (4) VP-focal **yalnız fırsatçı** (varsayılan
kapalı). (5) Düşük güvende: hızı koru + etiketle; istenirse overspeed eşiğine güven-bazlı
histerez (yanlış-pozitif ihlal azalır).
**Doğrulama:** Birim test — uyumlu kaynaklarda yüksek, ayrışmada düşük `scale_confidence`.

### P6 — `run_focal_bias()` + PnP eval kapsamı [small]
**Neden:** focal/HFOV varsayımının hıza etkisi **hiç ölçülmemiş**; iki ajan çelişti.
Deney (§4.1.1 notu) PnP ppm'inin focal'a **bağışık** olduğunu gösterdi — yani bu büyük bir
bias **değil**, ama bu **özelliğin regresyon testiyle kilitlenmesi** gerekir (kimse var
olmayan bir bias'ı "düzeltmeye" kalkmasın) ve tilt-bağımlı artık (~%5) ölçülmeli. Ayrıca
PnP `eval/`'da **sıfır kapsama** (`focal|observe_plate_pose` grep=0).
**Ne:** `speed_noise_probe.py`'ye `run_focal_bias()` (GT'yi `f_gt` ile üret, estimator
HFOV=55° varsaysın, ScaleField-only yolda MAE tara) ve §D **PnP-kurtarma** kolu (köşeleri
çeşitli yaw'da üret + Gauss köşe jitter'ı σ=0.5-3px + focal-mismatch; kabul oranı =
`observe_plate_pose True`/`plate_ppm` None-değil, ve ppm hata medyanı). Jitter+mismatch
döngüselliği kırar.
**Doğrulama:** `pytest` — `ppm_err(HFOV±10°)` küçük/lineer; `recovery_rate(yaw=45)` >
`plate_ppm` yolu (PnP açılı plakaları kurtarır).

### Destekleyici küçük kazanımlar (quick wins)
- **harsh_braking kalibre kapısı [1 satır]:** `_check_harsh_braking` çağrısını
  `and vehicle.speed_is_calibrated` ile koşulla — ısınmada sezgisel hızdan yanlış
  Kritik-mod tetiğini önler (`pipeline.py:346`).
- **ByteTrack re-ID zaman-boşluğu [small]:** ardışık örnek `Δt > max(0.5, 4/fps)` ise
  baz-çizgisi koşusunu **böl** (mevcut "en uzun temiz koşu" altyapısını yeniden kullan,
  zaman-boşluğunu da "kesinti" say); boşluk-üstü hızı harsh_braking sinyali sayma.
- **Derinliğe-uyarlı pencere [medium]:** ufuktan giren araçta kare-başı Δs jitter
  mertebesine iner; pencereyi aktif ölçek kaynağından (homografi `_local_ppm_homography`,
  değilse `ppm_at`) türetilen metrik baz `min_baseline_m`'yi (~0.5 m) aşana dek büyüt;
  `foot_history`/`ts_history maxlen = max(12, 2*speed_window_frames)` bağla (uzun baz fiilen mümkün olsun).

> **Mimari ilke (değişmedi):** Tüm bu işler füzyon önceliğini (§7.1: Homografi → PnP-ppm(y)
> → sezgisel) ve mock-first (cv2 opsiyonel) kısıtını korur; hiçbiri "kamera bilinmiyor"
> varsayımını ihlal eden yeni bir dış girdi sokmaz. **Elenen başlıca öneri:** "VP-focal'ı
> PnP'ye bağla" — deney focal'ın ppm'de sadeleştiğini gösterdi, ölçek için gereksiz (§4.1.1).

---

### Kaynaklar

- Türk plaka standardı (Tip-1 520×120 mm): [OTORAF — Standart Plaka Ölçüleri](https://www.otoraf.com/standart-plaka-olculeri-nelerdir.html), [TSOF](https://www.tsof.org.tr/2016/039.pdf)
- Şerit genişliği ve kesik çizgi standartları: [KGM Karayolu Trafik İşaretleme Standartları](https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Trafik/IsaretlerElKitabi/KarayoluTrafikIsaretlemeStandartlari1.pdf), [Otoyol şerit genişliği](https://enpopulersorular.com/library/lecture/read/239947-otoyollarda-serit-genisligi-kac-metredir)
- Mevcut kod referansları: `ai/speed.py`, `ai/tracking.py`, `ai/PROGRESS.md` (R5), `config/settings.py`
