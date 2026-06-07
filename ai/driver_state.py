"""
Sürücü durumu — yorgunluk (EAR/PERCLOS), telefon, sigara, kemer, kulaklık.

SÜRÜCÜ KİM? — kişi-bazlı seçim (geometrik yarı-bölme DEĞİL):
  Araç kabinindeki 'person' tespitleri arasından, KAMERANIN BAKIŞ AÇISINA göre
  EN SAĞ-ALTTAKİ kişi SÜRÜCÜ kabul edilir; kalan tüm kişiler YOLCU sayılır.
  "Sağ-alt" skoru: score = right_w*(x2/W) + bottom_w*(y2/H), en yüksek = sürücü
  (driver_select_*_weight ile ayarlanır). Sürücü ROI = sürücü kişinin kutusudur.

  Neden yarı-bölme bırakıldı: aracı statik sağ/sol yarıya bölmek yolcu↔sürücü
  ayrımında yetersizdi (yolcu sağ yarıya, sürücü sol yarıya taşabilir; eğik açı
  ikisini de aynı yarıya koyabilir). Kişi kutusu hem ayrımı netleştirir hem de
  MediaPipe'a tam sürücü crop'u verir.

  'person' tespiti yoksa (uzak/küçük araç, model person üretmedi) → eski
  geometrik yarı-ROI'ye (Türkiye LHD: sağ yarı = sürücü) GÜVENLİ ŞEKİLDE düşülür.

RİSK YALNIZCA SÜRÜCÜ: telefon/sigara/kulaklık ve MediaPipe geometrisi YALNIZCA
sürücü kişinin kutusuna düşerse risk bayrağı yakar. Yolcu kutusundaki telefon
driver.passenger_phone=True olarak yalnızca KAYIT edilir (risk skoruna girmez);
yolcuların diğer hareketleri (el-yüz geometrisi) hiç analiz edilmez çünkü
MediaPipe yalnızca sürücü crop'unda çalışır.

TELEFON / SİGARA / KULAKLIK TESPİTİ — neden MediaPipe geometrisi?
  COCO ön-eğitimli YOLO 'cigarette'/'headphone' sınıfını bilmez, 'cell phone'u da
  araç-içi küçük nesne olarak güvenilmez yakalar. Bu yüzden bu üç ihlal,
  MediaPipe Hands (21 el landmark'ı) + FaceMesh (kulak/ağız) GEOMETRİSİNDEN
  çıkarılır:
    - El, KULAĞA yakın + N kare sürekli  → telefon (kulağa götürme)
    - Parmak ucu, AĞIZA yakın + tekrarlı → sigara
  Mesafeler YÜZ GENİŞLİĞİNE oranlanır → ölçek-bağımsız (yakın/uzak yüz fark etmez).
  Eşikler config/settings.py'de (K3). Kütüphane yoksa mock'a düşülür (K4).
  YOLO detections yolu da KORUNUR: model bir gün bu sınıfları üretirse (fine-tune)
  geometri ile OR'lanır — biri bile pozitifse bayrak yanar.
"""
from __future__ import annotations

import math
from collections import deque
from typing import List, Optional, Tuple

import numpy as np

from ai.schema import Detection, DriverState, BBox
from config.settings import get_settings

EAR_THRESHOLD = 0.21
PERCLOS_WINDOW = 30       # ~1 sn @30fps
PERCLOS_FATIGUE = 0.40    # %40 üstü -> yorgun

# MediaPipe Face Mesh göz landmark indeksleri
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]
# Ağız bölgesi (üst dudak ortası = 13, alt dudak ortası = 14)
_MOUTH_UPPER = 13
_MOUTH_LOWER = 14
# Yüz yan konturu (genişlik ölçeği + kulak yaklaşığı): sağ-yan=234, sol-yan=454
_FACE_SIDE_R = 234
_FACE_SIDE_L = 454
# El parmak uçları (MediaPipe Hands): başparmak,işaret,orta,yüzük,serçe
_FINGERTIPS = (4, 8, 12, 16, 20)


def _ear(pts) -> float:
    p = np.asarray(pts, dtype=float)
    a = np.linalg.norm(p[1] - p[5])
    b = np.linalg.norm(p[2] - p[4])
    c = np.linalg.norm(p[0] - p[3])
    return (a + b) / (2.0 * c) if c > 1e-6 else 0.0


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class DriverMonitor:
    def __init__(self, mode: str = "auto"):
        self.s = get_settings()
        self.mode = self._resolve(mode)
        self._mesh = None
        self._hands = None
        self._eye_closed = deque(maxlen=PERCLOS_WINDOW)
        # Telefon/sigara: pencere içinde "kaç kare aday" sayımıyla teyit (gürültü filtresi)
        win = max(1, self.s.driver_state_window)
        self._phone_hist = deque(maxlen=win)
        self._smoke_hist = deque(maxlen=win)
        self._headphone_hist = deque(maxlen=win)
        self._latch = {}   # {'phone': kalan_kare, 'smoke': ...} — süregelen davranış kilidi
        self._face_cache = None   # (geom_norm, kalan_kare) — yüz kaybolunca son konumu kısa süre kullan
        self._box_cache = {}      # {'phone': (BBox, kalan_kare), 'smoke': ...} — kutu latch ile senkron
        # ── Sürücü kimlik kilidi (vehicle_id → durum) ──
        self._driver_lock = {}     # vid → kilitli person track_id
        self._driver_cand = {}     # vid → [aday person id, ardışık kare sayımı]
        self._driver_miss = {}     # vid → kilitli sürücü kaç karedir kayıp (TTL sayacı)
        self._driver_last_box = {} # vid → son bilinen sürücü kutusu (geçici kayıpta ROI tut)
        if self.mode == "real":
            try:
                import mediapipe as mp
                self._mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False, max_num_faces=2, refine_landmarks=True,
                    min_detection_confidence=self.s.driver_face_conf,
                    min_tracking_confidence=self.s.driver_face_conf,
                )
                if self.s.driver_mp_hands:
                    self._hands = mp.solutions.hands.Hands(
                        static_image_mode=False, max_num_hands=2,
                        min_detection_confidence=self.s.driver_hand_conf,
                        min_tracking_confidence=self.s.driver_hand_conf,
                    )
            except Exception:
                self.mode = "mock"

    @staticmethod
    def _resolve(mode: str) -> str:
        mode = (mode or "auto").lower()
        if mode in ("real", "mock"):
            return mode
        try:
            import mediapipe  # noqa: F401
            return "real"
        except Exception:
            return "mock"

    def _prep_roi(self, roi: np.ndarray, cv2) -> np.ndarray:
        """
        Sürücü ROI'sini MediaPipe'a hazırlar: küçükse hedef boya büyütür, loşsa
        gamma + CLAHE ile parlatır. Dış sabit kamerada sürücü uzak/karanlık
        olduğundan bu olmadan FaceMesh/Hands yüzü/eli yakalayamaz.
        Büyütme yalnızca algılamayı kolaylaştırır; eşikler oran-bazlı olduğu için
        ölçüm bozulmaz. Dönüş: (işlenmiş_roi, uygulanan_büyütme_oranı).
        Büyütme oranı, native (gerçek) yüz boyutunu geri hesaplamak için lazım
        (uzak-yüz bastırma eşiği için).
        """
        scale = 1.0
        try:
            rh0, rw0 = roi.shape[:2]
            short = min(rh0, rw0)
            if 0 < short < self.s.driver_roi_min_px:
                scale = min(self.s.driver_roi_max_upscale, self.s.driver_roi_min_px / short)
                roi = cv2.resize(roi, (int(rw0 * scale), int(rh0 * scale)),
                                 interpolation=cv2.INTER_CUBIC)
            if self.s.driver_roi_brighten:
                # Gamma (gölgeleri aç) + L kanalında CLAHE (yerel kontrast)
                g = self.s.driver_roi_gamma
                if g and abs(g - 1.0) > 1e-3:
                    lut = np.array([((i / 255.0) ** (1.0 / g)) * 255
                                    for i in range(256)], dtype=np.uint8)
                    roi = cv2.LUT(roi, lut)
                lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
                roi = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        except Exception:
            pass
        return roi, scale

    # ── Kare işleme: FaceMesh + Hands TEK SEFER (yorgunluk/telefon/sigara paylaşır) ──
    def _process_real(self, frame: np.ndarray, driver_roi: Optional[BBox]):
        """
        Sürücü ROI crop'unu BİR kez FaceMesh ve Hands'ten geçirir.

        Dönüş: (face_lm, hands_px, roi_gray, rh, rw, scale, ox, oy)
          face_lm  : ilk yüzün landmark listesi (normalize, 0..1) | None
          hands_px : her el için [(x,y), ...] ROI-piksel koordinatları (liste)
          roi_gray : ROI'nin gri tonu (parlak-piksel sigara yedeği için) | None
          rh, rw   : ROI yükseklik/genişlik (px, büyütme SONRASI)
          scale    : uygulanan büyütme oranı (native yüz boyutunu geri hesaplamak için)
          ox, oy   : ROI'nin tam-karedeki sol-üst ofseti (px). ROI-px → tam-kare:
                     x_full = x_roi/scale + ox  (kutu görselleştirme/çıktı için).
        Önceki kod FaceMesh'i yorgunluk + sigara için AYRI AYRI işliyordu; burada
        tek process ile ~2× MediaPipe maliyeti kazanılır.
        """
        try:
            import cv2
        except Exception:
            return None, [], None, 0, 0, 1.0, 0, 0

        h, w = frame.shape[:2]
        if driver_roi:
            x1, y1 = max(0, int(driver_roi.x1)), max(0, int(driver_roi.y1))
            x2, y2 = min(w, int(driver_roi.x2)), min(h, int(driver_roi.y2))
            roi = frame[y1:y2, x1:x2]
        else:
            x1 = y1 = 0
            roi = frame
        if roi.size == 0:
            return None, [], None, 0, 0, 1.0, 0, 0

        # ── Ön-işleme: dış kamerada sürücü uzak+karanlık → büyüt + parlat ──
        roi, scale = self._prep_roi(roi, cv2)

        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        rh, rw = roi.shape[:2]

        face_lm = None
        if self._mesh is not None:
            fres = self._mesh.process(rgb)
            if fres.multi_face_landmarks:
                face_lm = fres.multi_face_landmarks[0].landmark

        hands_px: List[List[Tuple[float, float]]] = []
        if self._hands is not None:
            hres = self._hands.process(rgb)
            if hres.multi_hand_landmarks:
                for hand in hres.multi_hand_landmarks:
                    hands_px.append([(lm.x * rw, lm.y * rh) for lm in hand.landmark])

        return face_lm, hands_px, roi_gray, rh, rw, scale, x1, y1

    # ── Yorgunluk: paylaşılan yüz landmark'larından EAR/PERCLOS ──
    def _fatigue_from_face(self, face_lm, rh: int, rw: int) -> Tuple[Optional[float], float, bool]:
        if face_lm is None:
            self._eye_closed.append(0)
            return None, self._perclos(), False

        def pick(idx):
            return [(face_lm[i].x * rw, face_lm[i].y * rh) for i in idx]

        ear = (_ear(pick(_LEFT_EYE)) + _ear(pick(_RIGHT_EYE))) / 2.0
        self._eye_closed.append(1 if ear < EAR_THRESHOLD else 0)
        perclos = self._perclos()
        return round(ear, 3), perclos, perclos > PERCLOS_FATIGUE

    def _perclos(self) -> float:
        if not self._eye_closed:
            return 0.0
        return round(sum(self._eye_closed) / len(self._eye_closed), 3)

    def _fatigue_mock(self, frame: np.ndarray) -> Tuple[Optional[float], float, bool]:
        b = float(frame.mean()) if frame is not None and frame.size else 128.0
        ear = round(0.30 - (1.0 - min(b, 255) / 255.0) * 0.18, 3)
        self._eye_closed.append(1 if ear < EAR_THRESHOLD else 0)
        perclos = self._perclos()
        return ear, perclos, perclos > PERCLOS_FATIGUE

    @staticmethod
    def _face_geom_norm(face_lm):
        """
        Yüz landmark'larından NORMALİZE (0..1) geometri çıkarır: (pr, pl, mouth).
          pr, pl : yüz yan-konturu (234 sağ, 454 sol) — genişlik/kulak yaklaşığı
          mouth  : üst+alt dudak ortası
        Normalize saklanır → ROI boyu (büyütme) değişse de cache geçerli kalır.
        Yüz yoksa None.
        """
        if face_lm is None:
            return None
        pr = (face_lm[_FACE_SIDE_R].x, face_lm[_FACE_SIDE_R].y)
        pl = (face_lm[_FACE_SIDE_L].x, face_lm[_FACE_SIDE_L].y)
        mu, ml = face_lm[_MOUTH_UPPER], face_lm[_MOUTH_LOWER]
        mouth = ((mu.x + ml.x) / 2, (mu.y + ml.y) / 2)
        return pr, pl, mouth

    @staticmethod
    def _hand_box(hand):
        """El landmark'larından sınırlayıcı kutu (ROI-px): (minx, miny, maxx, maxy)."""
        xs = [p[0] for p in hand]; ys = [p[1] for p in hand]
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _roi_box_to_full(box, scale: float, ox: int, oy: int, pad: float = 0.15) -> BBox:
        """ROI-px kutusunu TAM-KARE BBox'a çevirir (büyütmeyi geri al + ofset ekle).
        pad: kutuyu biraz genişletir (el + nesne görsel olarak rahat sığsın)."""
        x1, y1, x2, y2 = box
        sc = max(scale, 1e-6)
        fx1 = x1 / sc + ox; fy1 = y1 / sc + oy
        fx2 = x2 / sc + ox; fy2 = y2 / sc + oy
        bw = (fx2 - fx1) * pad; bh = (fy2 - fy1) * pad
        return BBox(x1=fx1 - bw, y1=fy1 - bh, x2=fx2 + bw, y2=fy2 + bh)

    def _box_latch(self, key: str, box_full, active: bool):
        """Kutuyu latch ile senkron tutar: yeni kutu varsa tazele; yoksa flag açık
        kaldığı sürece son kutuyu kullan. Dönüş: o an gösterilecek BBox | None."""
        n = self.s.driver_latch_frames
        if box_full is not None:
            self._box_cache[key] = (box_full, max(n, 1))
            return box_full
        cached = self._box_cache.get(key)
        if active and cached is not None and cached[1] > 0:
            self._box_cache[key] = (cached[0], cached[1] - 1)
            return cached[0]
        return None

    # ── Telefon / sigara / kulaklık: el-yüz geometrisi ──
    def _detect_phone_smoke(self, geom_px, hands_px, scale: float = 1.0):
        """
        Bu KARE için aday tespitleri döndürür (sürdürme teyidi assess'te yapılır):
          phone_cand : el (herhangi nokta) kulağa, yüz-genişliğinin oranından yakınsa
          smoke_cand : parmak ucu ağıza, yüz-genişliğinin oranından yakınsa
          hand_at_ear: kulaklık sezgisi için ham "el kulakta" sinyali
          phone_box  : telefonu tetikleyen elin kutusu (ROI-px) | None
          smoke_box  : sigarayı tetikleyen elin kutusu (ROI-px) | None

        geom_px = (pr, pl, mouth) — PİKSEL koordinatlarında yüz yan-konturu + ağız.
        Gerçek yüzden YA DA kısa süreli yüz cache'inden gelir (assess kurar). Cache
        sayesinde yüz kaybolsa da elin bulunduğu karelerde geometri hesaplanabilir.
        Geometri/yüz yoksa karşılaştırma referansı yok → hepsi False.
        """
        if geom_px is None or not hands_px:
            return False, False, False, None, None

        pr, pl, mouth = geom_px
        face_w = _dist(pr, pl)
        if face_w < 1e-3:
            return False, False, False, None, None

        # Uzak/küçük yüz kapısı: native (büyütme öncesi) yüz genişliği eşiğin
        # altındaysa el-parmak landmark'ları gürültülü → güvenilmez, bastır.
        if (face_w / max(scale, 1e-6)) < self.s.driver_min_face_px:
            return False, False, False, None, None

        ears = [pr, pl]  # kulak/yan-yüz yaklaşığı

        phone_thr = self.s.driver_phone_ear_ratio * face_w
        smoke_thr = self.s.driver_smoke_mouth_ratio * face_w

        phone_cand = smoke_cand = hand_at_ear = False
        phone_box = smoke_box = None
        for hand in hands_px:
            d_ear = min(_dist(pt, e) for pt in hand for e in ears)
            tips = [hand[i] for i in _FINGERTIPS if i < len(hand)]
            d_mouth = min((_dist(t, mouth) for t in tips), default=9e9)
            # AYRIM = parmak ucu AĞIZA mı yoksa KULAĞA mı daha yakın? (göreli yakınlık)
            # NEDEN: yüz profilde/küçükken kulak↔ağız birbirine yakındır; mutlak
            # "kulakta mı" testi sigarayı (el ağızda) telefon sanıp bastırıyordu.
            # Göreli kıyas video_1 (sigara) ile video_2 (telefon) ayrımını net yapar
            # (ölçüm: R_rel → video_1 %13 yakalar, video_2'de telefon sigaraya karışmaz).
            if d_mouth < smoke_thr and d_mouth <= d_ear:
                smoke_cand = True            # parmak ağızda (kulaktan yakın) → sigara
                smoke_box = self._hand_box(hand)
            elif d_ear < phone_thr and d_ear < d_mouth:
                phone_cand = True            # el kulakta (ağızdan yakın) → telefon
                hand_at_ear = True
                phone_box = self._hand_box(hand)
        return phone_cand, smoke_cand, hand_at_ear, phone_box, smoke_box

    def _detect_smoking_brightpixel(self, roi_gray: np.ndarray, face_lm, rh: int, rw: int) -> bool:
        """
        Ağız üstünde ince/parlak yatay nesne (sigara) arayan CV yedeği.
        El geometrisi sigarayı kaçırdığında (el kadrajda değilse) destekler.
        Paylaşılan roi_gray + face_lm kullanır (ikinci MediaPipe process YOK).
        """
        if roi_gray is None or face_lm is None:
            return False
        try:
            import cv2
            mx = int(face_lm[_MOUTH_UPPER].x * rw)
            my = int(face_lm[_MOUTH_UPPER].y * rh)
            sig_y1 = max(0, my - 80); sig_y2 = max(0, my - 10)
            sig_x1 = max(0, mx - 40);  sig_x2 = min(rw, mx + 40)
            if sig_y1 >= sig_y2 or sig_x1 >= sig_x2:
                return False
            region = roi_gray[sig_y1:sig_y2, sig_x1:sig_x2]
            if region.size == 0:
                return False
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
            enh = clahe.apply(region)
            _, thresh = cv2.threshold(enh, 180, 255, cv2.THRESH_BINARY)
            cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                _, _, rw2, rh2 = cv2.boundingRect(c)
                if rw2 < 8 or rh2 < 2:
                    continue
                if (rw2 / max(rh2, 1)) >= 3.0 and rw2 * rh2 > 20:   # ince yatay (~sigara)
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def driver_roi(vehicle_bbox: Optional[BBox], frame_shape) -> Optional[BBox]:
        """
        GEOMETRİK YEDEK (kişi tespiti yoksa). Türkiye LHD + önden kamera:
        Sürücü kameranın SAĞ tarafında → araç bbox sağ yarısı.
        Kabin yüksekliği: araç yüksekliğinin üst %70'i (camdan içeri).
        Asıl seçim kişi-bazlıdır → bkz. select_rois().
        """
        if not vehicle_bbox:
            return None
        v = vehicle_bbox
        w = v.x2 - v.x1
        h = v.y2 - v.y1
        mid_x = v.x1 + 0.5 * w
        # Sürücü: sağ yarı, kabin üst bölgesi
        return BBox(
            x1=mid_x,
            y1=v.y1 + 0.05 * h,
            x2=v.x2 - 0.02 * w,
            y2=v.y1 + 0.80 * h,
        )

    @staticmethod
    def passenger_roi(vehicle_bbox: Optional[BBox], frame_shape) -> Optional[BBox]:
        """GEOMETRİK YEDEK (kişi tespiti yoksa). Yolcu: araç bbox sol yarısı."""
        if not vehicle_bbox:
            return None
        v = vehicle_bbox
        w = v.x2 - v.x1
        h = v.y2 - v.y1
        mid_x = v.x1 + 0.5 * w
        return BBox(
            x1=v.x1 + 0.02 * w,
            y1=v.y1 + 0.05 * h,
            x2=mid_x,
            y2=v.y1 + 0.80 * h,
        )

    @staticmethod
    def _overlaps(a: BBox, b: BBox) -> bool:
        return not (a.x2 < b.x1 or a.x1 > b.x2 or a.y2 < b.y1 or a.y1 > b.y2)

    @staticmethod
    def _center_in(inner: BBox, outer: BBox) -> bool:
        """inner kutusunun merkezi outer (araç) kutusunun içinde mi?
        Kabin sakini ile yoldan geçen yayayı ayırt etmek için: yaya araç kutusuna
        kenardan değse bile merkezi dışarıda kalır → elenir."""
        return (outer.x1 <= inner.cx <= outer.x2) and (outer.y1 <= inner.cy <= outer.y2)

    def select_rois(self, detections: List[Detection], vehicle_bbox: Optional[BBox],
                    frame_shape, vehicle_id: Optional[int] = None
                    ) -> Tuple[Optional[BBox], List[BBox], bool]:
        """
        Kişi-bazlı sürücü/yolcu ayrımı + KİMLİK KİLİDİ.

        Araç kabinindeki 'person' tespitleri arasından KAMERANIN BAKIŞ AÇISINA göre
        EN SAĞ-ALTTAKİ kişiyi sürücü seçer; kalan kişiler yolcudur. Aynı kişi
        driver_lock_frames ardışık karede sürücü seçilirse o kişiye (ByteTrack
        track_id) KİLİTLENİR → araç yarı kadraj dışına çıksa bile sürücü arka
        koltuğa atlamaz (bkz. _resolve_driver, driver_lock_*).

        Dönüş: (driver_box, passenger_boxes, driver_is_person)
          driver_box        : sürücü ROI'si (kişi kutusu; yoksa geometrik sağ-yarı)
          passenger_boxes   : yolcu kişi kutuları (risk-dışı bölge listesi)
          driver_is_person  : sürücü gerçek bir 'person' tespitinden mi seçildi?
                              (False → geometrik yedek; belirsiz ihlal davranışı değişir)

        'person' tespiti yoksa veya kişi-bazlı seçim kapalıysa geometrik yedeğe düşer.
        """
        if not vehicle_bbox:
            return None, [], False

        if not getattr(self.s, "driver_person_select", True):
            return self.driver_roi(vehicle_bbox, frame_shape), [], False

        persons = [d for d in detections
                   if d.label == "person" and self._center_in(d.bbox, vehicle_bbox)]
        if not persons:
            # Kişi yok → eski geometrik davranış (güvenli yedek)
            return self.driver_roi(vehicle_bbox, frame_shape), [], False

        H = float(frame_shape[0]) if frame_shape and frame_shape[0] else 1.0
        W = float(frame_shape[1]) if frame_shape and len(frame_shape) > 1 and frame_shape[1] else 1.0
        rw = float(getattr(self.s, "driver_select_right_weight", 1.0))
        bw = float(getattr(self.s, "driver_select_bottom_weight", 1.0))

        def bottom_right_score(d: Detection) -> float:
            # Kutunun SAĞ-ALT köşesi (x2,y2) ne kadar sağ-altta → o kadar yüksek skor
            return rw * (d.bbox.x2 / W) + bw * (d.bbox.y2 / H)

        br = max(persons, key=bottom_right_score)
        driver = self._resolve_driver(vehicle_id, persons, br)

        if driver is None:
            # Kilitli sürücü geçici kayıp (TTL içinde) → KİMSEYİ sürücü yapma; davranış
            # bayraklarını latch tutar. ROI'yi son bilinen sürücü kutusunda tut ki
            # MediaPipe boş bölgeye baksın, bir yolcuyu sürücü sanmasın.
            vid = vehicle_id if vehicle_id is not None else -1
            last = self._driver_last_box.get(vid)
            return last, [d.bbox for d in persons], (last is not None)

        self._remember_driver_box(vehicle_id, driver.bbox)
        passengers = [d.bbox for d in persons if d is not driver]
        return driver.bbox, passengers, True

    def _resolve_driver(self, vehicle_id: Optional[int], persons: List[Detection],
                        br: Detection) -> Optional[Detection]:
        """
        Kimlik kilidi makinesi. Döndürür:
          Detection → bu karenin sürücüsü (kilitli kişi mevcutsa o; değilse sağ-alt aday)
          None      → kilitli sürücü geçici kayıp (TTL içinde): kimseyi sürücü yapma

        person track_id yoksa (mock / takipçi kapalı) kilit kurulamaz → saf sağ-alt.
        """
        if not getattr(self.s, "driver_lock_enable", True):
            return br

        vid = vehicle_id if vehicle_id is not None else -1
        by_id = {d.track_id: d for d in persons if d.track_id is not None}

        locked = self._driver_lock.get(vid)
        if locked is not None:
            if locked in by_id:
                self._driver_miss[vid] = 0
                return by_id[locked]                 # kilitli sürücü mevcut → HEP o
            # Kilitli sürücü bu karede yok (araç yarı çıktı / occlusion)
            miss = self._driver_miss.get(vid, 0) + 1
            self._driver_miss[vid] = miss
            if miss <= self.s.driver_lock_ttl:
                return None                          # bekle — sürücüyü başkasına verme
            # TTL doldu → kilidi bırak ve aşağıda yeniden edin
            for d in (self._driver_lock, self._driver_cand,
                      self._driver_miss, self._driver_last_box):
                d.pop(vid, None)

        # Kilit yok → sağ-alt adayı say (yalnız izlenebilir id varsa kilitlenebilir)
        brid = br.track_id
        if brid is None:
            return br
        cand = self._driver_cand.get(vid)
        if cand and cand[0] == brid:
            cand[1] += 1
        else:
            self._driver_cand[vid] = [brid, 1]
        if self._driver_cand[vid][1] >= self.s.driver_lock_frames:
            self._driver_lock[vid] = brid
            self._driver_miss[vid] = 0
        return br

    def _remember_driver_box(self, vehicle_id: Optional[int], box: BBox) -> None:
        vid = vehicle_id if vehicle_id is not None else -1
        self._driver_last_box[vid] = box

    def prune_locks(self, alive_vehicle_ids) -> None:
        """Sahnede olmayan araçların sürücü-kilidi durumunu temizle (bellek)."""
        keep = set(alive_vehicle_ids)
        keep.add(-1)   # vehicle_id=None tek-slotu daima korunur
        for store in (self._driver_lock, self._driver_cand,
                      self._driver_miss, self._driver_last_box):
            for k in [k for k in store if k not in keep]:
                del store[k]

    def _latch_flag(self, key: str, active: bool) -> bool:
        """
        Süregelen davranış kilidi: bayrak bu kare TEYİT edildiyse latch'i tazele;
        teyit yoksa kalan kare sayısınca bayrağı basılı tut, sonra bırak.
        Sürücü kısa süre kaybolsa/landmark kaçsa da (uzak/karanlık) davranış sürdüğü
        için bayrak titremez. Teyit zaten sustain gerektirdiğinden tek-kare FP latch'lenmez.
        """
        n = self.s.driver_latch_frames
        if n <= 0:
            return active
        if active:
            self._latch[key] = n
            return True
        rem = self._latch.get(key, 0)
        if rem > 0:
            self._latch[key] = rem - 1
            return True
        return False

    def assess(self, frame: np.ndarray, detections: List[Detection], profile: str,
               vehicle_bbox: Optional[BBox] = None,
               driver_bbox: Optional[BBox] = None,
               passenger_boxes: Optional[List[BBox]] = None,
               driver_is_person: Optional[bool] = None) -> DriverState:
        state = DriverState()

        frame_shape = frame.shape if frame is not None else (0, 0)
        # ROI'ler dışarıdan (pipeline'da bir kez hesaplanıp) geçirilebilir; yoksa
        # burada kişi-bazlı seçimle üretilir (testler assess'i tek başına çağırabilir).
        if driver_bbox is None and passenger_boxes is None:
            droi, passenger_boxes, driver_is_person = self.select_rois(
                detections, vehicle_bbox, frame_shape)
        else:
            droi = driver_bbox
            passenger_boxes = passenger_boxes or []
            if driver_is_person is None:
                driver_is_person = True

        # ── 1) YOLO detections yolu (model bu sınıfları üretirse — fine-tune sonrası) ──
        # RİSK YALNIZCA SÜRÜCÜ KUTUSU: ihlal yalnız sürücü kişinin kutusuna düşerse
        # bayrak yakar. Yolcu kutusundaki telefon yalnız KAYIT (passenger_phone).
        # Belirsiz (hiçbir kişiyle örtüşmeyen) telefon: yolcu varsa risk-dışı sayılır
        # (sürücü-dışı hareket riski etkilemesin); kabinde tek kişi/kişi yoksa
        # (yalnız sürücü ya da geometrik yedek) konservatif olarak sürücüye yazılır.
        if droi is not None:
            for d in detections:
                in_driver = self._overlaps(droi, d.bbox)
                in_passenger = any(self._overlaps(pb, d.bbox) for pb in passenger_boxes)

                if d.label == "phone":
                    if in_driver:
                        state.phone_use = True       # Sürücü telefon → tehlike
                    elif in_passenger:
                        state.passenger_phone = True # Yolcu telefon → kayıt ama tehlike değil
                    elif not passenger_boxes:
                        state.phone_use = True       # Tek sürücü / geometrik yedek → konservatif
                    else:
                        state.passenger_phone = True # Yolcu varken belirsiz → risk-dışı
                elif d.label == "cigarette":
                    if in_driver:
                        state.smoking = True
                elif d.label == "headphone":
                    if in_driver:
                        state.headphone = True

            # COCO'da emniyet kemeri sınıfı yok; fine-tune gelene kadar devre dışı
            state.no_seatbelt = False

        # Tetikleyen el kutuları (tam-kare) — real branch'te doldurulur, latch'te kullanılır
        phone_box_full = smoke_box_full = None

        # ── 2) MediaPipe geometri yolu (telefon/sigara/kulaklık) — yalnız kritik+real ──
        # Tüm MediaPipe analizi TEK kare işlemeyle yapılır; sonuçlar paylaşılır.
        if profile == "critical" and frame is not None and frame.size:
            if self.mode == "real":
                face_lm, hands_px, roi_gray, rh, rw, scale, ox, oy = self._process_real(frame, droi)

                # Yorgunluk (paylaşılan yüz landmark'ı)
                ear, perclos, fatigue = self._fatigue_from_face(face_lm, rh, rw)
                state.ear, state.perclos, state.fatigue = ear, perclos, fatigue

                # Yüz geometrisi: gerçek yüz varsa cache'i tazele; yoksa kısa süre
                # son bilinen konumu kullan (dış kamerada yüz seyrek, el sık bulunur).
                geom_norm = self._face_geom_norm(face_lm)
                if geom_norm is not None:
                    self._face_cache = (geom_norm, self.s.driver_face_cache_frames)
                elif self._face_cache is not None and self._face_cache[1] > 0:
                    geom_norm = self._face_cache[0]
                    self._face_cache = (geom_norm, self._face_cache[1] - 1)
                geom_px = None
                if geom_norm is not None and rw and rh:
                    (prx, pry), (plx, ply), (mxn, myn) = geom_norm
                    geom_px = ((prx * rw, pry * rh), (plx * rw, ply * rh),
                               (mxn * rw, myn * rh))

                # Telefon / sigara adayları (bu kare) + tetikleyen el kutuları (ROI-px)
                phone_cand, smoke_cand, hand_at_ear, phone_box, smoke_box = \
                    self._detect_phone_smoke(geom_px, hands_px, scale)
                # Sigara CV yedeği (opsiyonel, varsayılan kapalı — gerçek footage'ta FP yüksek):
                # el kadrajda olmasa da ağız üstü ince nesne. Telefon adayı varken çalıştırma.
                if (self.s.driver_smoke_brightpixel
                        and not smoke_cand and not phone_cand):
                    smoke_cand = self._detect_smoking_brightpixel(roi_gray, face_lm, rh, rw)

                # Tetikleyen el kutularını TAM-KARE koordinata çevir (görsel + çıktı)
                if phone_box is not None:
                    phone_box_full = self._roi_box_to_full(phone_box, scale, ox, oy)
                if smoke_box is not None:
                    smoke_box_full = self._roi_box_to_full(smoke_box, scale, ox, oy)

                # Sürdürme/tekrar penceresi → gürültüyü ele (anlık tek-kare false positive'i bastırır)
                self._phone_hist.append(1 if phone_cand else 0)
                self._smoke_hist.append(1 if smoke_cand else 0)
                self._headphone_hist.append(1 if (hand_at_ear and not phone_cand) else 0)

                if sum(self._phone_hist) >= self.s.driver_phone_sustain:
                    state.phone_use = True
                if sum(self._smoke_hist) >= self.s.driver_smoke_sustain:
                    state.smoking = True
                # Kulaklık (opsiyonel, düşük güven — varsayılan kapalı): el kulakta
                # sabit ama telefon teyidi yoksa. Telefon teyit edilirse kulaklık sayma.
                if (self.s.driver_headphone_enable and not state.phone_use
                        and sum(self._headphone_hist) >= self.s.driver_phone_sustain):
                    state.headphone = True
            else:
                # Mock: yorgunluk sentetik; telefon mock detector'dan detections yoluyla gelir
                ear, perclos, fatigue = self._fatigue_mock(frame)
                state.ear, state.perclos, state.fatigue = ear, perclos, fatigue

        # Latch — telefon/sigara süregelen davranış: teyit sonrası bayrağı basılı tut
        state.phone_use = self._latch_flag("phone", state.phone_use)
        state.smoking = self._latch_flag("smoke", state.smoking)

        # Kutuyu bayrakla senkron yayınla: bayrak açıkken son tetikleyen el kutusu
        pb = self._box_latch("phone", phone_box_full, state.phone_use)
        sb = self._box_latch("smoke", smoke_box_full, state.smoking)
        state.phone_bbox = pb if state.phone_use else None
        state.cigarette_bbox = sb if state.smoking else None

        return state
