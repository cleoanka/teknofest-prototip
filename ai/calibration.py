"""
Oto-kalibrasyon: piksel→metre ölçeği (ppm) sahnenin kendisinden türetilir.

Sorun (gercek_hiz_plani.md §1): sabit yol-kenarı kamerasında kamera yüksekliği/
açısı/odak verilmez. Metrik km/h için 1 pikselin yerde kaç metreye karşılık
geldiğini (ppm) bilmek şart. Dışarıdan alamayız → sahneden öğreniriz.

Bu modül Aşama 1'i (§4) uygular:
  • plaka_ppm()  — TR plakası 520 mm referansından yerel ppm (en kesin nokta ölçü).
  • ScaleField   — onlarca ölçümü görüntü-y'sine (derinlik vekili) göre toplayıp
                   ppm(y) eğrisi uydurur (perspektif: ufka yakın = uzak = küçük ppm).
  • MetricSpeedEstimator — ppm(y) ile aracın yer düzlemindeki metrik yer
                   değiştirmesini hesaplayıp v = Δs/Δt · 3.6 ile km/h üretir.

Aşama 2 (araç-genişliği yedeği), Aşama 3 (pencere/EMA/aykırı reddi) ve
Aşama 4 (şerit homografisi) bu sınıfları genişletir.
"""
from __future__ import annotations

from collections import deque
from typing import Optional, Tuple

import numpy as np

from ai.schema import BBox
from ai.tracking import Track, KalmanSpeed1D
from ai.homography import GroundHomography
from ai.plate_pnp import estimate_plate_pose, default_focal_px, PlatePose
from ai.vanishing_point import confidence_from_agreement


# TR Tip-1 plaka en/boy oranı: 520/120 ≈ 4.33. Plaka kameraya dik (cepheden)
# görünürken bu orana yakındır; açıyla (foreshortening) daralınca oran sapar →
# o ölçümü ppm için güvenilmez sayarız.
_PLATE_ASPECT = 520.0 / 120.0


def plate_ppm(plate_bbox: BBox, plate_width_m: float = 0.520,
              aspect_tolerance: float = 0.35) -> Optional[float]:
    """Plaka piksel genişliğinden yerel ölçeği (piksel/metre) döndür.

    Foreshortening koruması: en/boy oranı 520/120≈4.33'ten `aspect_tolerance`
    bağıl payından fazla saparsa plaka eğik görünüyordur → None (ölçümü düşür).
    """
    if plate_bbox is None or plate_width_m <= 0:
        return None
    w = plate_bbox.x2 - plate_bbox.x1
    h = plate_bbox.y2 - plate_bbox.y1
    if w <= 1 or h <= 1:
        return None
    aspect = w / h
    if abs(aspect - _PLATE_ASPECT) / _PLATE_ASPECT > aspect_tolerance:
        return None
    return w / plate_width_m


class ScaleField:
    """Görüntü dikey konumuna bağlı yerel ölçek alanı: ppm(y) = slope·y + intercept.

    Sabit kamerada derinlik ≈ y'nin tek-yönlü fonksiyonudur; bu yüzden ppm de
    y ile (yaklaşık doğrusal) değişir. Onlarca aracın plaka/araç ölçümü birikir,
    sağlam (aykırı-dayanıklı) bir doğru uydurulur. Yeterli y-yayılımı yoksa
    sabit ppm = medyan(ppm) kullanılır (tek derinlik varsayımı).
    """

    def __init__(self, min_samples: int = 6, maxlen: int = 4000):
        self.min_samples = max(2, min_samples)
        self._ys: deque = deque(maxlen=maxlen)
        self._ppms: deque = deque(maxlen=maxlen)
        self._ws: deque = deque(maxlen=maxlen)
        self._srcs: deque = deque(maxlen=maxlen)   # §12-P5 — kaynak etiketi (pnp/plate/vehicle)
        self._slope: float = 0.0
        self._intercept: float = 0.0
        self._median_ppm: float = 0.0
        self._fitted: bool = False

    def add(self, y: float, ppm: float, weight: float = 1.0,
            source: str = "plate") -> None:
        """Ölçüm ekle. weight = güven (1/sigma): plaka yüksek (1.0), araç-genişliği
        düşük (~0.25) — gürültülü kaynak az, kesin kaynak çok ağırlık alır.
        source = ölçek kaynağı (pnp/plate/vehicle) — §12-P5 kaynaklar-arası uyum için."""
        if ppm is None or ppm <= 0 or not np.isfinite(ppm) or weight <= 0:
            return
        self._ys.append(float(y))
        self._ppms.append(float(ppm))
        self._ws.append(float(weight))
        self._srcs.append(str(source))

    @property
    def n_samples(self) -> int:
        return len(self._ppms)

    @property
    def is_ready(self) -> bool:
        return self._fitted

    def fit(self) -> bool:
        """Birikmiş ölçümlerden ppm(y)'yi uydur. Başarılıysa True.

        Tek tur artık-bazlı aykırı reddi (|resid| > 2.5·MAD atılır) ile sağlamlaştırılır.
        """
        n = len(self._ppms)
        if n < self.min_samples:
            return False
        ys = np.asarray(self._ys, dtype=float)
        ppms = np.asarray(self._ppms, dtype=float)
        ws = np.asarray(self._ws, dtype=float)
        self._median_ppm = float(np.median(ppms))

        # y yeterince yayılmadıysa eğim güvenilmez → (ağırlıklı) sabit ppm
        if float(np.std(ys)) < 1e-3:
            self._slope = 0.0
            self._intercept = float(np.average(ppms, weights=ws))
            self._fitted = True
            return True

        slope, intercept = np.polyfit(ys, ppms, 1, w=ws)
        resid = ppms - (slope * ys + intercept)
        mad = float(np.median(np.abs(resid - np.median(resid)))) or 1e-9
        keep = np.abs(resid - np.median(resid)) <= 2.5 * mad
        if keep.sum() >= self.min_samples and keep.sum() < n:
            slope, intercept = np.polyfit(ys[keep], ppms[keep], 1, w=ws[keep])
        self._slope, self._intercept = float(slope), float(intercept)
        self._fitted = True
        return True

    def ppm_at(self, y: float) -> Optional[float]:
        """Verilen görüntü-y'sinde ppm. Uydurma yoksa veya tahmin fiziksel
        değilse (≤0) medyan ppm'e düşer."""
        if not self._fitted:
            return None
        val = self._slope * float(y) + self._intercept
        if not np.isfinite(val) or val <= 1e-6:
            return self._median_ppm if self._median_ppm > 0 else None
        return val

    def source_agreement(self) -> Optional[float]:
        """§12-P5 — KAYNAKLAR-ARASI ölçek uyumu (0..1) ya da None.

        Her kaynağın (pnp/plate/vehicle) ölçümünü fitlenen ppm(y)'ye göre BAĞIL ARTIK
        (ppm_i / ppm_at(y_i)) olarak normalize eder → kaynak-başı medyan alır. Bu, her
        kaynağın ortalama ölçek-yanlılığını y-dağılımından BAĞIMSIZ verir. ≥2 kaynak varsa
        medyanların yayılımından güven üretir (vanishing_point.confidence_from_agreement):
        kaynaklar hemfikirse (yayılım küçük) güven yüksek. <2 kaynak → None (çapraz-kontrol
        yapılamaz; sahte güven uydurma). Ground-truth gerektirmez, cv2-bağımsız."""
        if not self._fitted:
            return None
        ratios: dict = {}
        for y, ppm, src in zip(self._ys, self._ppms, self._srcs):
            base = self.ppm_at(y)
            if base and base > 0 and np.isfinite(ppm):
                ratios.setdefault(src, []).append(ppm / base)
        per_source = [float(np.median(v)) for v in ratios.values() if len(v) >= 2]
        if len(per_source) < 2:
            return None
        return confidence_from_agreement(per_source)


class MetricSpeedEstimator:
    """Sahneden öğrenilen ppm(y) ile metrik km/h üretir (Aşama 1).

    Pipeline örneği başına bir adet; kareler boyunca plaka ölçümlerini biriktirir
    (ısınma), yeterince ölçüm olunca ppm(y)'yi uydurur ve track'in yer-temas
    noktasının iki kare arası metrik yer değiştirmesinden hız hesaplar.

    Isınma tamamlanana kadar `estimate()` (None, False) döndürür → çağıran eski
    kalibrasyonsuz sezgisele düşer (is_calibrated=False).
    """

    def __init__(self, settings):
        self.s = settings
        self.scale = ScaleField(min_samples=getattr(settings, "calib_min_samples", 6))
        # track_id → KalmanSpeed1D; EMA'nın yerini aldı (titreme bastırma için)
        self._kalman: dict = {}
        # §12-P2 — track_id → deque[(ts, Z)]: plaka PnP'nin çözdüğü metrik derinlik
        # (kamera-uzayı Z) geçmişi. Homografi yokken boyuna hız dZ/dt'den, foreshortening
        # ten BAĞIMSIZ olarak türetilir (ppm(y) yatay ölçeği boyuna harekette undershoot eder).
        self._pnp_z_hist: dict = {}
        # Aşama 4 — şerit homografisi (kurulursa ppm(y)'ye göre ÖNCELİKLİ ölçek kaynağı)
        self.homography: Optional[GroundHomography] = None
        # Katman 2 — kamera odağı (px). camera_focal_px verilmezse ilk karede HFOV'den
        # türetilip burada saklanır; PnP ppm = focal/Z bu odağı kullanır.
        self._focal_px: Optional[float] = getattr(settings, "camera_focal_px", None)
        self._principal: Optional[Tuple[float, float]] = None
        # Çapraz doğrulama/teşhis için en son geçerli PnP pozu (yaw/pitch/reproj).
        self.last_pose: Optional[PlatePose] = None
        # §12-P5 — en son hesaplanan kaynaklar-arası ölçek güveni (0..1 / None).
        self.last_scale_confidence: Optional[float] = None

    def set_homography(self, homography: Optional[GroundHomography]) -> None:
        """Yer düzlemi homografisini ata (§7.1: B kaynağı A'dan önceliklidir)."""
        if homography is not None and not homography.is_valid:
            return
        self.homography = homography

    def observe_plate(self, plate_bbox: BBox) -> None:
        """Bir karede görülen plakadan yerel ppm örneği topla (ısınma).

        Plaka tek, dünya-sabiti, ~%1 varyanslı referans → yüksek ağırlık (1.0)."""
        ppm = plate_ppm(plate_bbox, self.s.plate_width_m,
                        getattr(self.s, "plate_aspect_tolerance", 0.35))
        if ppm is not None:
            # Plaka alt kenarı yere en yakın referans yüksekliği
            self.scale.add(plate_bbox.y2, ppm, weight=1.0, source="plate")

    def _ensure_intrinsics(self, frame_w: int, frame_h: int) -> Tuple[float, Tuple[float, float]]:
        """Odak (px) ve asal noktayı (görüntü merkezi) hazırla/cache'le.

        camera_focal_px verilmediyse yatay FOV varsayımından kare genişliğiyle
        türetilir (default_focal_px). Asal nokta görüntü merkezi alınır.
        """
        if self._focal_px is None or self._focal_px <= 1.0:
            self._focal_px = default_focal_px(
                frame_w, getattr(self.s, "camera_hfov_deg", 55.0))
        if self._principal is None:
            self._principal = (frame_w / 2.0, frame_h / 2.0)
        return self._focal_px, self._principal

    def observe_plate_pose(self, corners, frame_w: int, frame_h: int,
                           track_id: Optional[int] = None,
                           ts: Optional[float] = None) -> bool:
        """Katman 2/3 — plaka 4 köşesinden düzlemsel PnP ile foreshortening-bağımsız
        ppm topla (§4.1'in tam çözümü).

        plate_ppm() eğik plakayı (aspect sapması) atarken bu, açıyı çözerek o ölçümü
        KURTARIR: ppm = focal/Z açıdan bağımsızdır. Pose makul (Z aralıkta, tilt sınır
        altında, reprojeksiyon düşük) ise yüksek ağırlıkla ScaleField'e eklenir.

        §12-P2: track_id ve ts verilirse pose'un metrik derinliği (distance_m) bu track'in
        Z-geçmişine yazılır → estimate() homografi yokken dZ/dt'den boyuna hız hesaplar.

        Dönüş: True → pose kullanıldı (çağıran observe_plate'i ATLAMALI, çift sayım olmasın).
               False → pose çıkmadı; çağıran bbox tabanlı observe_plate'e düşmeli.
        """
        if not getattr(self.s, "plate_pnp_enabled", True) or corners is None:
            return False
        focal, pp = self._ensure_intrinsics(frame_w, frame_h)
        pose = estimate_plate_pose(
            corners, focal, pp,
            plate_w_m=self.s.plate_width_m,
            plate_h_m=getattr(self.s, "plate_real_height_mm", 112.0) / 1000.0,
            max_reproj_px=getattr(self.s, "plate_pnp_max_reproj_px", 6.0),
            min_distance_m=getattr(self.s, "plate_pnp_min_distance_m", 1.0),
            max_distance_m=getattr(self.s, "plate_pnp_max_distance_m", 120.0),
        )
        if pose is None:
            return False
        if pose.tilt_deg > getattr(self.s, "plate_pnp_max_tilt_deg", 60.0):
            return False
        if not np.isfinite(pose.ppm) or pose.ppm <= 0:
            return False
        # ppm(y) ölçek-alanını besle. Referans yükseklik: plakanın alt kenarı (yere yakın).
        y_ref = float(max(pt[1] for pt in corners))
        self.scale.add(y_ref, pose.ppm,
                       weight=getattr(self.s, "plate_pnp_weight", 1.2), source="pnp")
        self.last_pose = pose
        # §12-P2 — metrik derinliği track'in Z-geçmişine yaz (boyuna hız için)
        if track_id is not None and ts is not None and pose.distance_m > 0:
            hist = self._pnp_z_hist.get(track_id)
            if hist is None:
                hist = deque(maxlen=getattr(self.s, "pnp_z_hist_len", 12))
                self._pnp_z_hist[track_id] = hist
            hist.append((float(ts), float(pose.distance_m)))
        return True

    def observe_vehicle(self, vehicle_bbox: BBox, vtype: Optional[str]) -> None:
        """Aşama 2 — araç bbox genişliğinden sınıf-bazlı ppm yedeği (§4.2).

        Tekil araç genişliği ±%15-20 oynar (yandan görünümde bbox genişliği aracın
        BOYUNU verir → hata) ⇒ DÜŞÜK ağırlık. Çok araçtan istatistiksel olarak
        (ScaleField'in ağırlıklı + aykırı-dayanıklı regresyonu) sağlamlaşır.
        """
        if vehicle_bbox is None:
            return
        widths = getattr(self.s, "vehicle_width_m", {}) or {}
        typ_w = widths.get(vtype) or widths.get("car") or 1.80
        px_w = vehicle_bbox.x2 - vehicle_bbox.x1
        if px_w <= 1 or typ_w <= 0:
            return
        ppm = px_w / typ_w
        self.scale.add(vehicle_bbox.y2, ppm,
                       weight=getattr(self.s, "vehicle_ppm_weight", 0.25),
                       source="vehicle")

    def maybe_fit(self) -> None:
        """Yeterli ölçüm biriktiyse ppm(y)'yi (yeniden) uydur + §12-P5 güveni güncelle."""
        if self.scale.n_samples >= self.scale.min_samples:
            self.scale.fit()
            self.last_scale_confidence = self.scale.source_agreement()

    def _step_meters(self, f0, f1, use_homography: Optional[bool] = None) -> Optional[float]:
        """İki yer-temas noktası arası metrik yer değiştirme (m).

        Füzyon önceliği (§7.1): homografi varsa noktalar metrik yer düzlemine
        izdüşürülüp Öklid mesafe alınır (perspektif-tam); yoksa yerel ppm(y)
        ortalamasıyla pikselden metreye çevrilir (Aşama 1-2).

        `use_homography` açıkça verilirse o kaynak zorlanır (Problem 2 çapraz-
        kontrolü homografi yerine plaka ölçeğine düşmek için False geçer).
        """
        use_h = (self.homography is not None) if use_homography is None else use_homography
        (x0, y0), (x1, y1) = f0, f1
        if use_h and self.homography is not None:
            g0 = self.homography.to_ground(x0, y0)
            g1 = self.homography.to_ground(x1, y1)
            if g0 is None or g1 is None:
                return None
            return ((g1[0] - g0[0]) ** 2 + (g1[1] - g0[1]) ** 2) ** 0.5
        ppm0 = self.scale.ppm_at(y0)
        ppm1 = self.scale.ppm_at(y1)
        if not ppm0 or not ppm1:
            return None
        ppm = 0.5 * (ppm0 + ppm1)
        return (((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5) / ppm

    def _local_ppm_homography(self, x: float, y: float) -> Optional[float]:
        """Homografinin (x, y) pikselinde ima ettiği yerel ppm (piksel/metre).

        1 px yatay ve dikey adımın yer düzleminde kaç metreye karşılık geldiğinden
        türetilir → işaret-tabanlı homografi ölçeğini, plaka/araç ölçek-alanıyla
        kıyaslanabilir bir ppm'e çevirir (Problem 2 çapraz-kontrolü)."""
        if self.homography is None:
            return None
        g = self.homography.to_ground(x, y)
        gx = self.homography.to_ground(x + 1.0, y)
        gy = self.homography.to_ground(x, y + 1.0)
        if g is None or gx is None or gy is None:
            return None
        dh = ((gx[0] - g[0]) ** 2 + (gx[1] - g[1]) ** 2) ** 0.5     # 1px yatay → m
        dv = ((gy[0] - g[0]) ** 2 + (gy[1] - g[1]) ** 2) ** 0.5     # 1px dikey → m
        m_per_px = 0.5 * (dh + dv)
        return (1.0 / m_per_px) if m_per_px > 1e-9 else None

    def _homography_scale_conflict(self, foot) -> bool:
        """Problem 2 (§B): homografi ölçeği, işaretten-BAĞIMSIZ plaka/araç ölçek-
        alanıyla `speed_scale_check_factor` katından fazla ayrışıyor mu?

        Homografi yanlış yol-tipi yüzünden kayabilir (ör. şehir içi 6 m kesik-çizgi
        adımını otoyol 12 m sanmak → 2× şişme). TR plakası 520 mm bundan bağımsız
        mutlak çapadır; gross ayrışmada homografiye değil plakaya güveniriz."""
        if self.homography is None or not self.scale.is_ready:
            return False
        x, y = foot
        ppm_h = self._local_ppm_homography(x, y)
        ppm_a = self.scale.ppm_at(y)
        if not ppm_h or not ppm_a or ppm_h <= 0 or ppm_a <= 0:
            return False
        factor = getattr(self.s, "speed_scale_check_factor", 1.8)
        return max(ppm_h, ppm_a) / min(ppm_h, ppm_a) > factor

    def _homography_longitudinal_conflict(self, track: Track) -> bool:
        """§12-P4 — homografinin BOYUNA ölçeği (dash_pitch) PnP derinlik hızıyla gross
        ayrışıyor mu? PnP dZ/dt focal/dash_pitch'ten BAĞIMSIZ bir boyuna referanstır;
        homografi hızı bunun `speed_scale_check_factor` katından fazlaysa dash_pitch
        muhtemelen yanlış (ör. şehir 6m'yi otoyol 12m sanmak → 2× boyuna şişme — eski
        izotropik ppm-çakışma geçidi bunu eşik altına seyreltip kaçırıyordu).

        Yalnız boyuna hareket anlamlıyken (v_radial taban üstü) tetiklenir; saf yanal
        harekette (Z~sabit, v_radial~0) bağımsız boyuna referans yok → işaretlenmez."""
        if self.homography is None:
            return False
        v_radial = self._radial_speed_mps(track)
        if v_radial is None:
            return False
        if v_radial < getattr(self.s, "speed_pnp_conflict_floor_mps", 2.0):
            return False
        v_homog = self._robust_speed_mps(track, True)
        if v_homog is None or v_homog <= 0:
            return False
        factor = getattr(self.s, "speed_scale_check_factor", 1.8)
        return max(v_homog, v_radial) / min(v_homog, v_radial) > factor

    def _robust_speed_mps(self, track: Track, use_homography: bool) -> Optional[float]:
        """Titreme-dayanıklı hız (m/s) — **uzun baz-çizgisi** yaklaşımı.

        Hızı kare-kare anlık hızların medyanından DEĞİL, pencerenin uçtan-uca tek
        metrik yer değiştirmesinden hesaplar: Δs penceresi büyür, piksel titremesi
        sabit kalır → jitter/Δs oranı küçülür (kare-kare medyana göre σ=2px'te MAE
        ~%40 düşük, eval/speed_noise_probe §C).

        Önemli: ivme reddini **anlık** hızlara uygulamayız — jitter'lı anlık hızlar
        eşiği aşıp temiz pencereyi parçalardı. Yalnız **teleport** (baz-çizginin
        ≫ üstündeki tekil sıçrama) reddedilir; teleportlar pencereyi böler, en uzun
        temiz koşunun uçtan-uca yer değiştirmesi alınır (test: teleport reddi)."""
        foots = list(track.foot_history)
        tss = list(track.ts_history)
        base_window = max(1, getattr(self.s, "speed_window_frames", 6))

        # §12 quick-win — derinliğe-uyarlı pencere: ufka-kaçan araçta kare-başı metrik
        # Δs jitter mertebesine iner (speed_noise_probe §C). Pencereyi metrik baz
        # min_baseline_m'yi aşana dek geriye büyüt → uzakta jitter/Δs küçülür. Yakın
        # alanda baz zaten büyük → pencere base_window'da kalır (nötr, ekstra gecikme yok).
        window = base_window
        min_baseline_m = getattr(self.s, "speed_min_baseline_m", 0.0)
        if min_baseline_m > 0 and len(foots) > base_window + 1:
            maxw = len(foots) - 1
            while window < maxw:
                a = len(foots) - 1 - window
                m = self._step_meters(foots[a], foots[-1], use_homography)
                if m is not None and m >= min_baseline_m:
                    break
                window += 1

        pairs = []   # (i, anlık_hız_mps)  — i = sonraki foot indeksi
        for i in range(max(1, len(foots) - window), len(foots)):
            t0, t1 = tss[i - 1], tss[i]
            if t0 is None or t1 is None or (t1 - t0) <= 0:
                continue
            meters = self._step_meters(foots[i - 1], foots[i], use_homography)
            if meters is None:
                continue
            pairs.append((i, meters / (t1 - t0)))
        if not pairs:
            return None

        def endpoint_speed(a: int, b: int) -> Optional[float]:
            """a→b foot indeksleri arası uçtan-uca metrik hız (uzun baz-çizgisi)."""
            m = self._step_meters(foots[a], foots[b], use_homography)
            dt = tss[b] - tss[a]
            return (m / dt) if (m is not None and dt > 0) else None

        # §12 quick-win — zaman-boşluğu (ByteTrack re-ID / kare düşmesi) eşiği: normal
        # kare aralığının katı + mutlak taban. Bunu AŞAN adım, baz-çizgisini bölen bir
        # "kesinti" sayılır (boşluk boyunca aracın gerçek ilerlemesi tek adıma yığılıp
        # hızı çarpıtmasın, ani-fren/ivme maskelenmesin). Düşük-fps'te yanlış bölmeyi
        # önlemek için eşik medyan adım süresine uyarlanır.
        step_dts = [tss[i] - tss[i - 1] for (i, _) in pairs]
        med_dt = float(np.median(step_dts)) if step_dts else 0.0
        gap_floor = getattr(self.s, "speed_max_gap_s", 0.5)
        max_gap = max(gap_floor, 4.0 * med_dt) if med_dt > 0 else gap_floor
        gap_idx = {i for (i, _) in pairs if (tss[i] - tss[i - 1]) > max_gap}

        # Tüm pencere uç-nokta baz-çizgisi (jitter-dayanıklı taban)
        v_base = endpoint_speed(pairs[0][0] - 1, pairs[-1][0])
        if v_base is None:
            v_base = float(np.median([v for _, v in pairs]))

        # Teleport reddi: baz-çizginin ≫ üstündeki tekil sıçramalar (jitter DEĞİL).
        # Eşik bağıl (3×) + mutlak taban → düşük hızda jitter'ı yanlış işaretlemez.
        floor = getattr(self.s, "speed_max_accel_mps2", 8.0)
        thr = max(3.0 * abs(v_base), 3.0 * floor)
        good = sorted(i for (i, v) in pairs if abs(v) <= thr and i not in gap_idx)
        if len(good) == len(pairs):
            return v_base                             # teleport/boşluk yok → tam pencere baz-çizgisi
        if not good:
            return float(np.median([v for _, v in pairs]))

        # Teleport VEYA zaman-boşluğu var → en uzun kesintisiz temiz koşunun uçtan-uca bazı
        runs, cur = [], [good[0]]
        for i in good[1:]:
            if i == cur[-1] + 1:
                cur.append(i)
            else:
                runs.append(cur)
                cur = [i]
        runs.append(cur)
        best = max(runs, key=len)
        v = endpoint_speed(best[0] - 1, best[-1])
        return v if v is not None else v_base

    def _radial_speed_mps(self, track: Track) -> Optional[float]:
        """§12-P2 — PnP derinlik geçmişinden |dZ/dt| (boyuna/radyal hız, m/s).

        Uzun baz-çizgisi: pencere uçlarındaki Z farkı / zaman farkı. PnP Z örnekleri
        seyrektir (yalnız 4-köşeli plaka karelerinde) → kare-kare değil uçtan-uca alınır;
        köşe titremesinin Z'ye sızması böyle bastırılır. Foreshortening'den bağımsızdır
        (PnP açıyı zaten çözdü). İşaret yok (yaklaşan/uzaklaşan fark etmez)."""
        hist = self._pnp_z_hist.get(track.track_id)
        if not hist or len(hist) < getattr(self.s, "speed_pnp_z_min_samples", 2):
            return None
        samples = list(hist)
        (t0, z0), (t1, z1) = samples[0], samples[-1]
        dt = t1 - t0
        if dt < getattr(self.s, "speed_pnp_z_min_dt_s", 0.2):
            return None
        if not (np.isfinite(z0) and np.isfinite(z1)):
            return None
        return abs(z1 - z0) / dt

    def _lateral_speed_mps(self, track: Track) -> float:
        """Yatay (image-x) piksel hareketinden yanal yer hızı (m/s), ppm(y) ile.

        Boyuna hareketin x-izdüşümünü de içerir (yol-kenarı kamerasında saf yanal
        değildir); ancak merkezli şeritte/uzak araçta küçüktür ve radyal (dZ/dt) ile
        birleştirilir. ppm hazır değilse 0 döner (yalnız radyal kalır)."""
        foots = list(track.foot_history)
        tss = list(track.ts_history)
        window = max(1, getattr(self.s, "speed_window_frames", 6))
        idxs = [i for i in range(max(0, len(foots) - window - 1), len(foots))
                if i < len(tss) and tss[i] is not None]
        if len(idxs) < 2:
            return 0.0
        a, b = idxs[0], idxs[-1]
        dt = tss[b] - tss[a]
        if dt <= 0:
            return 0.0
        dx_px = abs(foots[b][0] - foots[a][0])
        ppm0 = self.scale.ppm_at(foots[a][1])
        ppm1 = self.scale.ppm_at(foots[b][1])
        if not ppm0 or not ppm1:
            return 0.0
        ppm = 0.5 * (ppm0 + ppm1)
        return (dx_px / ppm) / dt

    def _depth_fused_speed_mps(self, track: Track) -> Optional[float]:
        """§12-P2 — homografi YOKKEN boyuna+yanal füzyon hızı (m/s).

        v = √(v_radial² + v_lateral²): v_radial = |dZ/dt| (PnP derinlik, foreshortening-
        bağımsız — ppm(y)'nin boyuna undershoot'unu giderir), v_lateral = yatay piksel ×
        ppm(y). Z geçmişi yetersizse None → çağıran eski ppm(y) yoluna düşer."""
        if not getattr(self.s, "speed_depth_fusion_enabled", True):
            return None
        v_radial = self._radial_speed_mps(track)
        if v_radial is None:
            return None
        v_lateral = self._lateral_speed_mps(track)
        return (v_radial ** 2 + v_lateral ** 2) ** 0.5

    def estimate(self, track: Optional[Track]) -> Tuple[Optional[float], bool]:
        """(km/h, is_calibrated) döndür. Ölçek hazır değilse (None, False).

        Problem 1 (titreme): pencere içi ivme-reddi + en uzun temiz koşunun
        uçtan-uca tek yer değiştirmesi (uzun baz-çizgisi) + track-başı **Kalman**.
        Problem 2 (ölçek): homografi, işaretten-bağımsız plaka/araç ölçek-alanıyla
        gross ayrışırsa (yanlış yol-tipi) homografiyi bırakıp plaka çapasına düşer.
        """
        if track is None:
            return None, False
        # Metrik kaynak gerekli: homografi (B) ya da ppm(y) ölçek-alanı (A) hazır olmalı
        if self.homography is None and not self.scale.is_ready:
            return None, False

        use_h = self.homography is not None
        # Problem 2 — homografi ölçeği plaka çapasıyla çakışıyorsa ona güvenme
        foot_last = track.foot_history[-1] if len(track.foot_history) else None
        if use_h and foot_last is not None and self._homography_scale_conflict(foot_last):
            use_h = False
        # §12-P4 — homografi boyuna ölçeği (dash_pitch) PnP derinlik hızıyla gross
        # ayrışıyorsa (yanlış yol-tipi) homografiye güvenme, derinlik-füzyonuna düş.
        if use_h and self._homography_longitudinal_conflict(track):
            use_h = False

        if use_h:
            v_robust = self._robust_speed_mps(track, True)
        else:
            # §12-P2 — homografi yokken önce PnP derinlik-füzyonu (boyuna undershoot'u
            # giderir); Z geçmişi yoksa eski ppm(y) yer-değiştirme yoluna düş.
            v_robust = self._depth_fused_speed_mps(track)
            if v_robust is None:
                v_robust = self._robust_speed_mps(track, False)
        if v_robust is None:
            return None, False

        # Kalman filtresi — kareler arası kalan titremeyi bastırır (KalmanSpeed1D)
        q = getattr(self.s, "speed_kalman_q", 3.0)
        r = getattr(self.s, "speed_kalman_r", 8.0)
        tid = track.track_id
        if tid not in self._kalman:
            self._kalman[tid] = KalmanSpeed1D(Q=q, R=r)
        v_smooth = self._kalman[tid].update(v_robust)

        v_kmh = round(max(0.0, min(v_smooth * 3.6, self.s.speed_metric_max_kmh)), 1)
        return v_kmh, True

    def prune(self, active_ids) -> None:
        """Tracker'da artık olmayan track'lerin Kalman + PnP-Z durumunu temizle (bellek)."""
        for tid in [t for t in self._kalman if t not in active_ids]:
            del self._kalman[tid]
        for tid in [t for t in self._pnp_z_hist if t not in active_ids]:
            del self._pnp_z_hist[tid]
