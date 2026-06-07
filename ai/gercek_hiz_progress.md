# Gerçek (Metrik) Hız — İlerleme Günlüğü

> Kapsam: `gercek_hiz_plani.md`'nin uygulanışı. Plan = **ne/neden**; bu dosya = **yapıldı/ölçüldü**.
> Genel YZ günlüğü `ai/PROGRESS.md`'dedir; bu dosya yalnız **metrik hız** iş kolunu izler.
> Son güncelleme: **2026-06-07**

---

## Durum Özeti

| Aşama | İş | Durum | Kanıt |
|---|---|---|---|
| 0 | Zaman ekseni (gerçek Δt/PTS) | ✅ | `Track.dt_last()`, yarı-süre→2×hız testi |
| 1 | Plaka ppm + ppm(y) ölçek-alanı | ✅ | sentetik ppm=10 → 72.0 km/h analitik |
| 2 | Araç-genişliği yedeği + füzyon | ✅ | araç-only → 18 km/h; plaka çapası baskın |
| 3 | Pencere + aykırı reddi + Kalman | ✅ | ışınlanma adımı reddi; KalmanSpeed1D |
| 4 | Şerit homografisi (perspektif-tam) | ✅ | homografi 2 m/0.1 s → 72 km/h, MAE 0.00 |
| 5 | Sentetik + çapraz-yöntem + `speed_eval` | ✅ | B MAE 0.00; overspeed P=R=1.00 |
| 6 | Kaçış noktası (VP) self-kalibrasyon | ✅ | f=800 geri kazanımı; üç-yöntem uyumu |
| **2+** | **Köşe-tabanlı PnP (foreshortening-bağımsız ölçek)** | ✅ | 35° yaw'da PnP %3, naif genişlik %10+ |

**Füzyon önceliği (§7.1, değişmedi):** Homografi (B) > PnP-beslenmiş ppm(y) (A) > kalibrasyonsuz sezgisel.

> **Not (2026-06-07 akşam):** Yukarıdaki ✅'ler **birim/sentetik düzeyde** geçerlidir.
> Adversaryal kod denetimi (aşağı) bazılarının **üretime tam bağlanmadığını** ortaya
> koydu (özellikle Aşama 6 VP ve §8.2 çapraz-doğrulama). Dürüst durum için bkz.
> "Denetim — Plan↔Kod Boşlukları".

---

## Denetim — Adversaryal Kod-Temelli Geliştirme Taraması (2026-06-07, akşam)

39-ajanlık bir workflow ile metrik hız altsistemi **gerçek kodun üstünde** tarandı
(6 boyut paralel inceleme → her aday "çürütücü" ajanla doğrulama). **32 aday → 9
doğrulanmış** (is_real ∧ is_correct ∧ güven≥0.5). Önemlisi: dokümandaki bazı ✅'lerin
kodda karşılığı **yok**. Planın "ne/neden"ine §12 olarak eklendi; burası "ne bulundu".

### Plan↔Kod boşlukları (✅ diyor ama kod demiyor)
- **Aşama 6 VP üretimde ÖLÜ:** `ai/vanishing_point.py` (`vanishing_point`,
  `focal_from_orthogonal_vps`, `methods_agree`, `confidence_from_agreement`) yalnız
  testlerde + bu .md'lerde + `plate_pnp.py:69` docstring'inde geçiyor; `pipeline.py`/
  `calibration.py`'de **hiç import edilmiyor**. Birim-test'li ama pipeline'a bağlı değil.
- **§8.2 çapraz-doğrulama YAPILMADI:** `last_pose` (`calibration.py:219`) saklanıyor
  ama hiçbir üretim yolu **okumuyor**; `estimate()` sabit `return v_kmh, True`
  (`calibration.py:399`) — nicel güven yok, `methods_agree` çağrılmıyor.
- **Eval döngüsel:** `speed_eval.py:135-136` izi `g2i`'den üretip aynı `i2g`'yi
  `set_homography` ile veriyor → `MAE~0` kaçınılmaz (yalnız cebir/birim kanıtı).
  Oto-kalibrasyonun **gerçek** doğruluğu (§1'deki %10-15 hedefi) hiç ölçülmedi.
- **Canlı "5G" Δt bozuk:** `frontend/app.js:111` ve `tools/camera_client.py:59` yalnız
  `{frame}` gönderiyor — `client_ts` **yok** → `backend/main.py:1110` `client_ts=None`
  → `pipeline.py:266` `vts=t0=time.time()` (wall-clock). Canlı akışta Δt = sunucuya
  **varış** farkı; ağ jitter'ı/kuyruk doğrudan `v=Δs/Δt`'ye giriyor. (Offline `tools/
  test_video.py` gerçek PTS besliyor — sorun yalnız canlı yolda.)
- **harsh_braking kalibre kapısı yok:** `_check_harsh_braking` (`pipeline.py:222`)
  yalnız `speed_kmh is not None` ile çağrılıyor; ısınmada **kalibrasyonsuz** sezgisel
  hız -50 km/h/s eşiğini yanlış tetikleyip anında Kritik moda geçirebilir.

### Çözülen çelişki — HFOV/focal varsayımı hıza geçer mi? (DENEY)
İki ajan çelişti: biri "HFOV ±10° → hız ±%10 sistematik bias", diğeri "ppm=focal/Z'de
focal sadeleşir, ~%0". **Gerçek `estimate_plate_pose` ile deney** (f_gt ile köşe üret →
f_assumed=55°-HFOV ile çöz, ppm hatası):

| true HFOV | yaw=0° | yaw=20° | yaw=40° |
|---|---|---|---|
| 45° | %0.0 | −%1.1 | −%4.0 |
| 50° | −%0.0 | −%0.6 | −%2.1 |
| 60° | +%0.0 | +%0.7 | +%2.3 |
| 65° | +%0.0 | +%1.4 | +%4.8 |

**Sonuç:** PnP ppm'i HFOV varsayımına **neredeyse bağışık** (cepheden %0; hata yalnız
yüksek tilt'te ve küçük). Çünkü H gözlenen piksellerden çözülür (focal'dan bağımsız) ve
`Z∝f` → `ppm=f/Z`'de focal sadeleşir. **Mutlak ölçek çapası focal DEĞİL, plakanın
520mm'sidir** (H'ye gömülü). Dolayısıyla "VP-focal'ı PnP'ye bağla" önerisi ppm doğruluğu
için **gereksiz** (elendi); VP'nin gerçek değeri §8.2 güven sinyalidir. `run_focal_bias()`
bu bağışıklığı **kilitleyen regresyon testi** olarak yine değerli (büyük bias düzeltmesi değil).

---

## Katman 2 — Plaka Köşelerinden Düzlemsel PnP (2026-06-07)

### Sorun (kullanıcı tespiti)
Plan §4.1: `ppm = w_piksel / 0.520`. Plaka kameraya **açılı (yaw)** görününce yatay
boyut `cos(yaw)` ile **daralır** → ppm şişer → mesafe/hız yanlışlanır. `plate_ppm()`
bunu aspect oranı sapmasıyla (520/120≈4.33'ten %35) tespit edip ölçümü **atıyordu**.
Açılı yol kamerasında plakaların çoğu hafif eğik → **çok ölçüm boşa gidiyordu**.

Kullanıcının sezgisi: "araç sağa/sola dönünce genişlik kısalır, yüksekliğe göre hesaplasak?"
→ matematiksel sonucu: yaw'a karşı `W_etkin = 4.33·h`. Ama yükseklik (i) ~%5 piksel
gürültüsü (plaka boyu eninin 1/4.7'si), (ii) pitch'e açık. Tek boyut seçmek yerine
**açıyı çözmek** doğru cevap.

### Çözüm — açıyı atmak yerine ÇÖZ
4 plaka köşesi + bilinen **520×112 mm** + odak uzaklığı → **düzlemsel PnP** ile plakanın
kamera-uzayı pozu (derinlik Z, yaw, pitch). Foreshortening artık bir hata değil,
**denklemin çözdüğü bilinmeyen**. Köşeler zaten `plate_crop.perspective_correct()`'ten
geliyordu (cleoanka'nın perspektif düzeltmesi) → **bedava girdi**.

### Modüller
- **`ai/plate_pnp.py` (YENİ):** `estimate_plate_pose(corners, focal, pp)` →
  `PlatePose(distance_m, ppm, yaw_deg, pitch_deg, reproj_px)`.
  - Yöntem: **Zhang düzlemsel homografi ayrıştırması** — model→görüntü homografisi
    `H = K·[r1 r2 t]`, `K⁻¹H` sütunlarından R,t geri kazanılır. **Saf numpy**
    (`homography._solve_homography` yeniden kullanıldı), **cv2 GEREKMEZ** (K4 mock-first).
  - Çıktı ölçek: **`ppm = focal / Z`** → o derinlikteki görüntü-düzlemi ölçeği,
    **foreshortening'den bağımsız**. Eğik plakada bile doğru.
  - `default_focal_px(W, hfov)` — kalibre kamera yokken HFOV (≈55°) varsayımından
    `f = (W/2)/tan(HFOV/2)`. Gerçek focal VP'den (Aşama 6) gelirse override edilir.
  - Makullük geçitleri: reprojeksiyon RMS (`max_reproj_px`), Z aralığı, tilt sınırı,
    köşe sayısı/finite. Geçemezse `None` → çağıran eski `plate_ppm`'e düşer.
- **`ai/calibration.py`:** `MetricSpeedEstimator.observe_plate_pose(corners, w, h)` —
  PnP ppm'i `ScaleField`'e **plate_ppm'den yüksek ağırlıkla** (1.2 vs 1.0) besler;
  açıdan bağımsız olduğu için eğik plakaları **kurtarır**. `True` dönerse pipeline
  `observe_plate`'i **atlar** (çift sayım yok); `False` dönerse bbox-genişliği fallback.
  `_ensure_intrinsics()` focal/asal-nokta'yı ilk karede türetip cache'ler.
  `last_pose` → §8.2 çapraz doğrulama için yaw/pitch/reproj kaydı.
- **`ai/pipeline.py`:** Blok kalibrasyon beslemesi PnP-öncelikli; `plate_corners` varsa
  PnP, yoksa eski `plate_ppm` yolu. Kenar filtresi (`_near_frame_edge`) korundu.
- **`config/settings.py`:** `plate_pnp_enabled` (vars. açık), `camera_focal_px` (None→HFOV),
  `camera_hfov_deg=55`, `plate_pnp_weight=1.2`, `plate_pnp_max_reproj_px=6`,
  `plate_pnp_min/max_distance_m`, `plate_pnp_max_tilt_deg=60`.

### Ölçülen (sentetik kontrollü, §8.1)
`tests/test_plate_pnp.py` — **13 test**. Bilinen odak + bilinen pozdan (Z, yaw) köşeleri
analitik izdüşür, PnP ile geri çöz:
- Frontal: derinlik geri kazanımı **%2 içinde**, reprojeksiyon **<0.5 px**.
- `ppm = focal/Z` doğrulandı (%2 içinde); yaw=30° → **±3°** içinde geri kazanıldı.
- **Kanıt testi (`test_pnp_beats_naive_width_on_yaw`):** plaka **35° yaw**'da →
  naif genişlik-ppm **%10+ yanılır**, PnP **%3 içinde** kalır (`pnp_err < naive_err`).
- Füzyon: `observe_plate_pose` → ScaleField'e örnek ekleniyor; disabled flag / köşesiz → `False`.

**Tüm paket: 313 → 326 yeşil**, regresyon yok. Commit `ef61609`.

### Katman 2'nin rolü (mimaride)
PnP, **Yöntem A'yı güçlendirir**, B'nin (homografi) yerini almaz. Homografi varken o
hâlâ birincil (perspektif-tam). PnP'nin kattığı: homografi **yokken** (silik şerit/gece)
ppm(y) ölçek-alanını **sadece dik plakalardan değil, açılı plakalardan da** doğru besler
→ daha çok veri, daha sağlam regresyon.

---

## Uygulandı — P1–P6 + quick-win KODA DÖKÜLDÜ (2026-06-07, akşam)

Tüm öneriler uygulanıp test edildi: **313→…→343 → 358 yeşil** (+15 test), regresyon yok.
Tam gerekçe planın **§12**'sinde; aşağıda **ne yapıldı + ne ÖLÇÜLDÜ**.

| # | İş | Durum | Dokunulan | Ölçülen |
|---|---|---|---|---|
| P1 | Canlı akış Δt (kare-damgası/sayaç) | ✅ | `pipeline._video_timestamp`, `backend/main.py` (sayaç), `app.js`/`camera_client.py` (`client_ts`) | client_ts→frame_index/fps→wall-clock; 3 birim test |
| P2 | Boyuna hız: PnP `dZ/dt` füzyonu | ✅ | `calibration` (`_pnp_z_hist`, `_radial/_lateral/_depth_fused_speed_mps`), `pipeline` (track_id+ts) | bağımsız-GT'de **MAE 0.0** (ppm-only **68.7**) |
| P3 | Bağımsız-GT eval (döngüsel değil) | ✅ | `eval/speed_eval.run_independent_gt_eval` + pinhole projektör | PnP+derinlik MAE **0.0**, yalnız-ppm **MAPE %95.5** |
| P4 | Boyuna ölçek çapraz-kontrol (PnP derinlik) | ✅ | `calibration._homography_longitudinal_conflict` | homografi 2× şişerse dZ/dt'ye düşer (test) |
| P5 | `scale_confidence` (additif, §8.2) | ✅ | `ScaleField.source_agreement`, `schema.Vehicle.scale_confidence`, `vanishing_point` bağlandı | kaynaklar hemfikir→>0.8, %50 sapma→<0.6 |
| P6 | `run_focal_bias` + PnP-kurtarma eval | ✅ | `eval/speed_noise_probe` §D/§E | focal HFOV±10°→∓~%10; yaw60° naif %0 vs PnP %100 |
| QW | harsh_braking kalibre kapısı + ByteTrack boşluk-bölme + derinliğe-uyarlı pencere | ✅ | `pipeline`, `calibration._robust_speed_mps`, `tracking` (maxlen 16) | zaman-boşluğu testi; suite yeşil |

### Kritik ölçümler ve dürüst nüanslar
- **P3 bağımsız-GT (döngüselliği kırdı):** PnP+derinlik boyuna harekette **MAE 0.0**
  (oto-kalibrasyon zinciri DOĞRU); yalnız-ppm yolu **MAE 68.7 / MAPE %95.5** undershoot
  (36→1.5, 72→3.3 km/h) — döngüsel evalin gizlediği model-uyumsuzluğu artık niceliklendi.
- **P2'nin ÖDÜNLEŞMESİ (yeni öğrenilen):** derinlik-füzyonu boyuna undershoot'u (~%95)
  giderir AMA `ppm=focal/Z`'de `Z∝f` olduğundan `dZ/dt` **focal-oranı kadar yanlıdır**
  (HFOV ±10° → hız ∓~%10; ölçülen 45°→−%20, 65°→+%22). ppm YOLU ise focal-robust ama
  boyuna undershoot eder. **Mutlak çapa: ppm→plaka 520mm, dZ/dt→focal.** Net: füzyon
  undershoot'tan çok daha iyi; ama focal'ı VP'den kalibre etmek **artık daha değerli**
  (eskiden ppm-only'de focal önemsizdi — bkz. [[pnp-ppm-focal-invariance]] güncellendi).
- **PnP per-sample gürültüsü (§D, dürüst kısıt):** köşe jitter'ı σ=0.5px + küçük plaka
  (Z=8m, ~17px) → per-sample ppm hatası **~%20-23** (progress'in eski "PnP %3" iddiası
  GÜRÜLTÜSÜZdü). Düzlemsel PnP'nin küçük-baz derinlik belirsizliği. PnP'nin değeri per-frame
  kesinlik DEĞİL: (a) açılı plakayı KURTARMA (yaw60° naif %0 → PnP %100), (b) ScaleField'in
  aykırı-dayanıklı çok-örnekli regresyonunu besleme (tekil gürültü orada bastırılır).
- **P4 kapsamı:** "hibrit `k_long` Z-düzeltmesi" (homografiyi düzelterek koru) TAM uygulanmadı
  — homografi-ima-derinliği (yer-ileri) ile PnP kamera-derinliği arasındaki tilt-projeksiyon
  bağı naif oranı kirletiyor (kamera yatay bakmadıkça ≠ 2.0). Bunun yerine güvenli alt-küme:
  PnP `dZ/dt` bağımsız boyuna referansıyla **tespit→homografiyi bırak→derinlik-füzyonuna düş**.
  Tam hibrit düzeltme VP-focal bağlanınca tekrar değerlendirilmeli.

### Eski "Sıradaki" (artık uygulandı) — özgün öneriler referans için

Tam gerekçe + uygulama ipuçları planın **§12**'sinde. Özet (etki/çaba):

1. **[P1 · high/small] Canlı akış Δt'si — kare-zaman damgası.** `app.js:111` +
   `camera_client.py:59` → `client_ts` ekle; `pipeline.process`'e `frame_index`;
   `frame_ts None` ise `vts = frame_index/fps` (en kötü `time.monotonic()`). Wall-clock
   yerine ağ-jitter'dan bağımsız tek-tipli Δt. **Doğrulanmış gerçek boşluk.**
2. **[P2 · high/medium] Boyuna hız: PnP `dZ/dt` + ppm(y) undershoot.** Kameranın en güçlü
   çözdüğü sinyal (Z derinliği) hıza hiç bağlı değil; homografisiz kolda boyuna hareket
   ppm(y)'den **sistematik düşük** çıkıyor (`speed_eval.py:184`). track_id→deque[(ts,Z)]
   tut; `v_radial=|ΔZ|/Δt` uzun-baz; `v=√(v_radial²+v_lat²)`. Yalnız homografi yokken.
3. **[P3 · high/small] Bağımsız-GT eval (döngüselliği kır).** `test_plate_pnp._project`
   pinhole'unu kullan, `GroundHomography`'ye dokunma; uçtan-uca observe→fit→estimate→km/h
   MAE. §1'deki %10-15 ile kıyaslanabilir **ilk dürüst rakam**.
4. **[P4 · high/small] Anizotropik dash-pitch koruması.** `_local_ppm_homography`
   izotropik ortalama (`0.5*(dh+dv)`) 2× **boyuna-yalnız** şişmeyi eşik 1.8 altına
   seyreltip kaçırıyor. Yön-içi `dv/dh` self-tutarlılığı (eşik ~1.4-1.5) + hibrit
   `k_long=median(Z_homog/pose.distance_m)` ile homografiyi atmadan Z'yi düzelt.
5. **[P5 · medium/medium] §8.2 + `scale_confidence` (additive).** `methods_agree`/
   `confidence_from_agreement`'i bağla; `is_calibrated`'ı EZME (sezgisele düşürür) —
   `schema.Vehicle`'a additif `scale_confidence` ekle. cv2-bağımsız çekirdek: ScaleField
   kaynak-içi uyum (PnP-ppm vs plate_ppm vs araç-genişliği). VP'ye gerçek üretim rolü budur.
6. **[P6 · small] `run_focal_bias()`** — focal-bağışıklığını kilitleyen regresyon testi
   (yukarıdaki deney tablosu) + tilt-bağımlı artığı (~%5) ölç. Büyük bias değil; teyit.
7. **Destekleyici küçük kazanımlar:** harsh_braking'e `and vehicle.speed_is_calibrated`
   kapısı (1 satır); ByteTrack re-ID zaman-boşluğunda baz-çizgisini böl (`dt>max(0.5,4/fps)`);
   ufuktan giren araç için derinliğe-uyarlı pencere + `foot_history maxlen` bağlama;
   `speed_noise_probe.py`'ye §D PnP-kurtarma kolu (jitter+focal-mismatch altında recall/ppm).

> **Önemli düzeltme (focal):** Önceki "Focal kaynağı: VP-focal bağlanırsa ölçek iyileşir"
> önerisi **geçersiz** — deney PnP ppm'inin focal'a bağışık olduğunu gösterdi (bkz. yukarı).
> Mutlak çapa plaka 520mm; VP-focal ppm için gereksiz, yalnız §8.2 güven için anlamlı.
