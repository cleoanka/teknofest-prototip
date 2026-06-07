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
geliyordu (Hikmet'in perspektif düzeltmesi) → **bedava girdi**.

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

## Sıradaki (öneri)
- **§8.2 çapraz doğrulama bağlantısı:** `last_pose`'tan türetilen PnP-hızı ile homografi
  hızını `vanishing_point.methods_agree()` ile karşılaştırıp `speed_is_calibrated` güvenini
  buna göre raporla (üç yöntem yakınsa "yüksek güven").
- **Gerçek video doğrulaması:** PnP ppm'in açılı plakalarda `plate_ppm`'e göre kaç ölçümü
  kurtardığını gerçek footage'ta say (`eval/speed_eval.py`'ye PnP kolu ekle).
- **Focal kaynağı:** HFOV varsayımı yerine VP-focal (Aşama 6) bağlanırsa mutlak ölçek de iyileşir.
