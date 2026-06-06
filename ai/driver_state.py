"""
Sürücü durumu — yorgunluk (EAR/PERCLOS), telefon, sigara, kemer, kulaklık.

Türkiye LHD (sol direksiyonlu) araç varsayımı:
  Kamera önden bakıyorsa sürücü kameranın SAĞ tarafındadır.
  → Araç bbox'ının sağ yarısı = sürücü ROI, sol yarısı = yolcu ROI.

Telefon kullanımı yalnızca sürücü ROI'sindeyse tehlike olarak işaretlenir.
Yolcu ROI'sindeki telefon driver.passenger_phone=True olarak ayrı takip edilir.
"""
from __future__ import annotations

import hashlib
import math
from collections import deque
from typing import List, Optional, Tuple

import numpy as np

from ai.schema import Detection, DriverState, BBox
from ai.mp_cabin import CabinAnalyzer
from ai.mp_seatbelt import SeatbeltDetector

EAR_THRESHOLD = 0.21
PERCLOS_WINDOW = 30       # ~1 sn @30fps
PERCLOS_FATIGUE = 0.40    # %40 üstü -> yorgun

# MediaPipe Face Mesh göz landmark indeksleri
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]
# Ağız bölgesi (üst dudak üstü = 13, alt dudak altı = 14)
_MOUTH_UPPER = 13
_MOUTH_LOWER = 14
# Kulak/yan-yüz proxy noktaları (el-kulak yakınlığı için referans)
_EAR_RIGHT = 234   # kameradan bakınca sağ yan-yüz
_EAR_LEFT = 454    # sol yan-yüz
# Yüz imzası için kararlı landmark'lar (sürücü-değişti tespiti)
_SIG_POINTS = [33, 263, 1, 13, 61, 291, 10, 152, 234, 454]


def _ear(pts) -> float:
    p = np.asarray(pts, dtype=float)
    a = np.linalg.norm(p[1] - p[5])
    b = np.linalg.norm(p[2] - p[4])
    c = np.linalg.norm(p[0] - p[3])
    return (a + b) / (2.0 * c) if c > 1e-6 else 0.0


class DriverMonitor:
    def __init__(self, mode: str = "auto", settings=None):
        if settings is None:
            from config.settings import get_settings
            settings = get_settings()
        self.s = settings
        self.mode = self._resolve(mode)
        self._mesh = None
        self._eye_closed = deque(maxlen=PERCLOS_WINDOW)
        # MediaPipe Hands kabin analizörü (el-kulak/ağız yakınlığı → telefon/sigara füzyonu)
        self.cabin = CabinAnalyzer(settings=settings, mode=mode)
        # MediaPipe Pose kemer tespiti (gövde çapraz şerit heuristiği)
        self.seatbelt = SeatbeltDetector(settings=settings, mode=mode)
        # Sürücü kimliği: önceki kareye ait normalize yüz öznitelik vektörü (değişti tespiti)
        self._last_feats: Optional[List[float]] = None
        # Loş kare aydınlatması için gamma LUT (her karede yeniden üretmemek için bir kez)
        self._gamma_lut = np.array([((i / 255.0) ** 0.4) * 255 for i in range(256)], dtype=np.uint8)
        self._face_refs = None
        if self.mode == "real":
            try:
                import mediapipe as mp
                self._mesh = mp.solutions.face_mesh.FaceMesh(
                    static_image_mode=False, max_num_faces=2, refine_landmarks=True,
                    min_detection_confidence=0.4,
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

    def _enhance(self, crop: np.ndarray) -> np.ndarray:
        """
        Kabin crop'unu MediaPipe'a vermeden önce iyileştir.

        NEDEN: gerçek test verisi (kapalı otopark, 4K dış kamera) loş ve sürücü küçük.
        Ölçtük: ham 4K karede yüz ~%0-8; sıkı crop + aydınlatma + büyütme ile yüz bulundu.
          - Karanlıksa: gamma + CLAHE (luminance) ile aydınlat.
          - Crop küçükse: büyüt — MediaPipe girişi içeride küçülttüğü için minik yüz kaybolmasın.
        Eşikler config'te (mp_enhance_*). Kapatılabilir (mp_enhance_enabled=False).
        """
        if crop is None or crop.size == 0 or not getattr(self.s, "mp_enhance_enabled", True):
            return crop
        try:
            import cv2
            out = crop
            if float(out.mean()) < float(getattr(self.s, "mp_enhance_dark_below", 90.0)):
                out = cv2.LUT(out, self._gamma_lut)
                if out.ndim == 3:
                    ycc = cv2.cvtColor(out, cv2.COLOR_BGR2YCrCb)
                    ycc[..., 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(ycc[..., 0])
                    out = cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR)
            h, w = out.shape[:2]
            target = int(getattr(self.s, "mp_min_crop_px", 320))
            if 0 < w < target:
                scale = min(3.0, target / w)   # en çok 3× (aşırı büyütme gürültüyü artırır)
                out = cv2.resize(out, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            return out
        except Exception:
            return crop

    def _detect_smoking_heuristic(self, frame: np.ndarray, driver_roi: Optional[BBox]) -> bool:
        """
        El-ağız yakınlık tespiti (sigara içme heuristic).

        Kural: Sürücü ROI içinde yüz tespit edilirse, ağız landmark'ının
        20 piksel yakınında küçük parlak/beyaz piksel yoğunluğu varsa → sigara
        şüphesi. COCO'da sigara sınıfı olmadığı için CV tabanlı yedek yöntem.
        """
        if self._mesh is None or frame is None or frame.size == 0:
            return False
        try:
            import cv2
            # Sürücü ROI crop
            if driver_roi:
                h, w = frame.shape[:2]
                x1 = max(0, int(driver_roi.x1)); y1 = max(0, int(driver_roi.y1))
                x2 = min(w, int(driver_roi.x2)); y2 = min(h, int(driver_roi.y2))
                roi = frame[y1:y2, x1:x2]
            else:
                roi = frame
                x1, y1 = 0, 0

            if roi.size == 0:
                return False

            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            res = self._mesh.process(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
            if not res.multi_face_landmarks:
                return False

            lm = res.multi_face_landmarks[0].landmark
            rh, rw = roi.shape[:2]

            # Ağız koordinatı (piksel)
            mx = int(lm[_MOUTH_UPPER].x * rw)
            my = int(lm[_MOUTH_UPPER].y * rh)

            # Ağızın üstünde küçük bölge: sigara genellikle dudaktan dışarı uzanır
            # Ağız merkezinin 60px üstünde 80x20px pencere tara
            sig_y1 = max(0, my - 80)
            sig_y2 = max(0, my - 10)
            sig_x1 = max(0, mx - 40)
            sig_x2 = min(rw, mx + 40)

            if sig_y1 >= sig_y2 or sig_x1 >= sig_x2:
                return False

            region = rgb[sig_y1:sig_y2, sig_x1:sig_x2]
            if region.size == 0:
                return False

            # CLAHE ile kontrastı artır, beyaz/gri ince nesne ara
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
            enh = clahe.apply(region)
            _, thresh = cv2.threshold(enh, 180, 255, cv2.THRESH_BINARY)

            # İnce yatay nesne: genişlik >> yükseklik (sigara oranı ~10:1)
            cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                rx, ry, rw2, rh2 = cv2.boundingRect(c)
                if rw2 < 8 or rh2 < 2:
                    continue
                ar = rw2 / max(rh2, 1)
                if ar >= 3.0 and rw2 * rh2 > 20:
                    return True
        except Exception:
            pass
        return False

    def _fatigue_real(self, frame: np.ndarray, driver_roi: Optional[BBox]) -> Tuple[Optional[float], Optional[float], bool]:
        # Bu metot yüz mesh'ini TEK kez çalıştırır ve yorgunluğun yanı sıra
        # el-yüz füzyonu (ağız/kulak referansları) + sürücü kimliği için gereken
        # ham yüz verisini self._face_refs içine yazar (FPS için tek geçiş).
        # Crop, MediaPipe'a verilmeden önce _enhance ile iyileştirilir (loş/küçük);
        # cabin/seatbelt/sigara aynı iyileştirilmiş crop'u kullanır (koordinat tutarlı).
        self._face_refs = None
        h, w = frame.shape[:2]

        # Sürücü ROI varsa yalnızca o bölgeyi BGR olarak kırp
        if driver_roi:
            x1, y1 = max(0, int(driver_roi.x1)), max(0, int(driver_roi.y1))
            x2, y2 = min(w, int(driver_roi.x2)), min(h, int(driver_roi.y2))
            crop = frame[y1:y2, x1:x2]
        else:
            crop = frame

        if crop.size == 0:
            self._eye_closed.append(0)
            return None, self._perclos(), False

        crop = self._enhance(crop)   # loş otopark + küçük yüz → aydınlat/büyüt

        try:
            import cv2
            analyze = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB) if crop.ndim == 3 else crop
        except Exception:
            analyze = crop

        res = self._mesh.process(analyze)
        if not res.multi_face_landmarks:
            self._eye_closed.append(0)
            return None, self._perclos(), False

        lm = res.multi_face_landmarks[0].landmark
        rh, rw = analyze.shape[:2]

        def pick(idx):
            return [(lm[i].x * rw, lm[i].y * rh) for i in idx]

        # El-yüz füzyonu için referans noktaları (iyileştirilmiş crop piksel uzayında)
        mouth_xy = (
            (lm[_MOUTH_UPPER].x + lm[_MOUTH_LOWER].x) * 0.5 * rw,
            (lm[_MOUTH_UPPER].y + lm[_MOUTH_LOWER].y) * 0.5 * rh,
        )
        ear_xys = [(lm[_EAR_RIGHT].x * rw, lm[_EAR_RIGHT].y * rh),
                   (lm[_EAR_LEFT].x * rw, lm[_EAR_LEFT].y * rh)]
        face_width = math.dist(ear_xys[0], ear_xys[1])
        self._face_refs = {
            "crop": crop,                 # iyileştirilmiş BGR crop → cabin/seatbelt/sigara tekrar kullanır
            "mouth_xy": mouth_xy,
            "ear_xys": ear_xys,
            "face_width": face_width,
            "feats": self._face_features(lm, rw, rh),
        }

        ear = (_ear(pick(_LEFT_EYE)) + _ear(pick(_RIGHT_EYE))) / 2.0
        self._eye_closed.append(1 if ear < EAR_THRESHOLD else 0)
        perclos = self._perclos()
        return round(ear, 3), perclos, perclos > PERCLOS_FATIGUE

    @staticmethod
    def _face_features(lm, rw: float, rh: float) -> List[float]:
        """
        Göz-arası mesafeye normalize edilmiş yüz öznitelik vektörü.

        Ölçek-bağımsız (sürücü kameraya yakın/uzak fark etmez). Biyometrik kimlik
        DEĞİL — yalnızca 'aynı sürücü mü, değişti mi' ayrımı için kaba imza.
        Gerçek tanıma için ayrı yüz-embedding modeli (ör. ArcFace) gerekir.
        """
        pts = {i: (lm[i].x * rw, lm[i].y * rh) for i in _SIG_POINTS}
        base = math.dist(pts[33], pts[263]) or 1.0   # göz-arası mesafe = normalizasyon tabanı
        pairs = [(1, 13), (10, 152), (234, 454), (61, 291), (33, 1), (263, 1)]
        return [round(math.dist(pts[a], pts[b]) / base, 4) for a, b in pairs]

    def _driver_identity(self, feats: Optional[List[float]]) -> Tuple[Optional[str], bool]:
        """feats vektöründen kısa imza üretir ve önceki kareye göre değişimi ölçer."""
        if not feats:
            return None, False
        changed = False
        if self._last_feats and len(self._last_feats) == len(feats):
            dist = math.dist(feats, self._last_feats)        # L2 öznitelik farkı
            changed = dist > float(getattr(self.s, "driver_id_change_threshold", 0.18))
        self._last_feats = feats
        # Kısa kararlı imza (kuantalanmış vektörün hash'i) — <3KB için 8 hane yeterli
        quant = ",".join(f"{v:.2f}" for v in feats)
        sig = hashlib.sha1(quant.encode()).hexdigest()[:8]
        return sig, changed

    def _perclos(self) -> float:
        if not self._eye_closed:
            return 0.0
        return round(sum(self._eye_closed) / len(self._eye_closed), 3)

    def _fatigue_mock(self, frame: np.ndarray) -> Tuple[Optional[float], Optional[float], bool]:
        b = float(frame.mean()) if frame is not None and frame.size else 128.0
        ear = round(0.30 - (1.0 - min(b, 255) / 255.0) * 0.18, 3)
        self._eye_closed.append(1 if ear < EAR_THRESHOLD else 0)
        perclos = self._perclos()
        return ear, perclos, perclos > PERCLOS_FATIGUE

    @staticmethod
    def driver_roi(vehicle_bbox: Optional[BBox], frame_shape) -> Optional[BBox]:
        """
        Türkiye LHD + önden kamera:
        Sürücü kameranın SAĞ tarafında → araç bbox sağ yarısı.
        Kabin yüksekliği: araç yüksekliğinin üst %70'i (camdan içeri).
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
        """Yolcu: araç bbox sol yarısı."""
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

    def assess(self, frame: np.ndarray, detections: List[Detection], profile: str,
               vehicle_bbox: Optional[BBox] = None) -> DriverState:
        state = DriverState()
        self._face_refs = None

        droi = self.driver_roi(vehicle_bbox, frame.shape if frame is not None else (0, 0))
        proi = self.passenger_roi(vehicle_bbox, frame.shape if frame is not None else (0, 0))

        # Yorgunluk yalnızca kritik profilde güvenilir (yüksek çözünürlük)
        if profile == "critical" and frame is not None and frame.size:
            if self.mode == "real":
                ear, perclos, fatigue = self._fatigue_real(frame, droi)
            else:
                ear, perclos, fatigue = self._fatigue_mock(frame)
            state.ear, state.perclos, state.fatigue = ear, perclos, fatigue

        # ── MediaPipe Hands kabin füzyonu (yüz bulunduysa el-kulak/ağız yakınlığı) ──
        # NEDEN: telefon/sigara/kulaklık YOLO'da küçük/elle kapalı → kaçar.
        # El iskeleti davranışı nesneyi görmeden yakalar; YOLO ile VEYA'lanır (recall↑).
        if profile == "critical" and self.mode == "real" and self._face_refs:
            refs = self._face_refs
            # Yüz mesh ile aynı iyileştirilmiş crop → koordinatlar (ağız/kulak) birebir tutarlı
            sig = self.cabin.analyze(
                refs["crop"], mouth_xy=refs["mouth_xy"], ear_xys=refs["ear_xys"],
                face_width=refs["face_width"],
            )
            state.driver_present = True
            state.hands_detected = sig.hands_detected
            state.hand_near_ear = sig.hand_near_ear
            state.hand_near_mouth = sig.hand_near_mouth
            # Sürücü kimliği / değişim tespiti (geometrik imza)
            state.driver_signature, state.driver_changed = self._driver_identity(refs.get("feats"))

        if droi is not None:
            for d in detections:
                in_driver = self._overlaps(droi, d.bbox)
                in_passenger = proi is not None and self._overlaps(proi, d.bbox)

                if d.label == "phone":
                    if in_driver:
                        state.phone_use = True      # Sürücü telefon → tehlike
                    elif in_passenger:
                        state.passenger_phone = True  # Yolcu telefon → kayıt ama tehlike değil
                    else:
                        # Araç içinde ama bölge belirlenemedi → konservatif: sürücü say
                        state.phone_use = True

                elif d.label == "cigarette":
                    if in_driver:
                        state.smoking = True

                elif d.label == "headphone":
                    if in_driver:
                        state.headphone = True

        # ── Füzyon: MediaPipe el sinyali YOLO'yu güçlendirir (VEYA mantığı) ──
        # El kulağa yakın → telefonla konuşma (YOLO telefonu görmese bile tehlike).
        if state.hand_near_ear:
            state.phone_use = True
        # El ağıza yakın → sigara delili (CV heuristic'e ek üçüncü kanıt kaynağı).
        if state.hand_near_mouth:
            state.smoking = True

        # Sigara içme heuristic (COCO sigara sınıfı yok → CV yedek).
        # Yüz bulunduysa aynı iyileştirilmiş crop'u kullan (loş otoparkta daha isabetli).
        if not state.smoking and self.mode == "real" and profile == "critical":
            if self._face_refs:
                state.smoking = self._detect_smoking_heuristic(self._face_refs["crop"], None)
            else:
                state.smoking = self._detect_smoking_heuristic(frame, droi)

        # ── Emniyet kemeri: MediaPipe Pose + çapraz şerit heuristiği ──
        # Sürücü gövde ROI'sinde kemer şeridi aranır. Yüz bulunmasa da çalışır
        # (gövde görünürse yeter). no_seatbelt muhafazakâr (kanıt eksikse bayrak yok).
        if profile == "critical" and self.mode == "real" and droi is not None \
                and frame is not None and frame.size:
            # Yüz mesh ile aynı iyileştirilmiş crop varsa onu kullan; yoksa ROI'yi kırp+iyileştir
            if self._face_refs:
                belt_crop = self._face_refs["crop"]
            else:
                h, w = frame.shape[:2]
                sx1, sy1 = max(0, int(droi.x1)), max(0, int(droi.y1))
                sx2, sy2 = min(w, int(droi.x2)), min(h, int(droi.y2))
                belt_crop = self._enhance(frame[sy1:sy2, sx1:sx2]) if (sx2 > sx1 and sy2 > sy1) else None
            belt = self.seatbelt.detect(belt_crop)
            if belt.torso_found:
                state.seatbelt_on = belt.belt_on      # True=takılı, False=yok
                state.no_seatbelt = belt.no_seatbelt  # risk.py bu bayrağı kullanır

        return state
