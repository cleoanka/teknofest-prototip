"""
Sürücü durumu — yorgunluk (EAR/PERCLOS), telefon, sigara, kemer, kulaklık.

Türkiye LHD (sol direksiyonlu) araç varsayımı:
  Kamera önden bakıyorsa sürücü kameranın SAĞ tarafındadır.
  → Araç bbox'ının sağ yarısı = sürücü ROI, sol yarısı = yolcu ROI.

Telefon kullanımı yalnızca sürücü ROI'sindeyse tehlike olarak işaretlenir.
Yolcu ROI'sindeki telefon driver.passenger_phone=True olarak ayrı takip edilir.
"""
from __future__ import annotations

from collections import deque
from typing import List, Optional, Tuple

import numpy as np

from ai.schema import Detection, DriverState, BBox

EAR_THRESHOLD = 0.21
PERCLOS_WINDOW = 30       # ~1 sn @30fps
PERCLOS_FATIGUE = 0.40    # %40 üstü -> yorgun

# MediaPipe Face Mesh göz landmark indeksleri
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]
# Ağız bölgesi (üst dudak üstü = 13, alt dudak altı = 14)
_MOUTH_UPPER = 13
_MOUTH_LOWER = 14


def _ear(pts) -> float:
    p = np.asarray(pts, dtype=float)
    a = np.linalg.norm(p[1] - p[5])
    b = np.linalg.norm(p[2] - p[4])
    c = np.linalg.norm(p[0] - p[3])
    return (a + b) / (2.0 * c) if c > 1e-6 else 0.0


class DriverMonitor:
    def __init__(self, mode: str = "auto"):
        self.mode = self._resolve(mode)
        self._mesh = None
        self._eye_closed = deque(maxlen=PERCLOS_WINDOW)
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
        try:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if frame.ndim == 3 else frame
        except Exception:
            rgb = frame
        h, w = frame.shape[:2]

        # Sürücü ROI varsa yalnızca o bölgeyi analiz et
        if driver_roi:
            x1, y1 = max(0, int(driver_roi.x1)), max(0, int(driver_roi.y1))
            x2, y2 = min(w, int(driver_roi.x2)), min(h, int(driver_roi.y2))
            analyze = rgb[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1
        else:
            analyze = rgb
            offset_x, offset_y = 0, 0

        if analyze.size == 0:
            self._eye_closed.append(0)
            return None, self._perclos(), False

        res = self._mesh.process(analyze)
        if not res.multi_face_landmarks:
            self._eye_closed.append(0)
            return None, self._perclos(), False

        lm = res.multi_face_landmarks[0].landmark
        rh, rw = analyze.shape[:2]

        def pick(idx):
            return [(lm[i].x * rw, lm[i].y * rh) for i in idx]

        ear = (_ear(pick(_LEFT_EYE)) + _ear(pick(_RIGHT_EYE))) / 2.0
        self._eye_closed.append(1 if ear < EAR_THRESHOLD else 0)
        perclos = self._perclos()
        return round(ear, 3), perclos, perclos > PERCLOS_FATIGUE

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

        droi = self.driver_roi(vehicle_bbox, frame.shape if frame is not None else (0, 0))
        proi = self.passenger_roi(vehicle_bbox, frame.shape if frame is not None else (0, 0))

        # Yorgunluk yalnızca kritik profilde güvenilir (yüksek çözünürlük)
        if profile == "critical" and frame is not None and frame.size:
            if self.mode == "real":
                ear, perclos, fatigue = self._fatigue_real(frame, droi)
            else:
                ear, perclos, fatigue = self._fatigue_mock(frame)
            state.ear, state.perclos, state.fatigue = ear, perclos, fatigue

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

            # COCO'da emniyet kemeri sınıfı yok; fine-tune gelene kadar devre dışı
            state.no_seatbelt = False

        # Sigara içme heuristic (COCO sigara sınıfı yok → CV yedek)
        if not state.smoking and self.mode == "real" and profile == "critical":
            state.smoking = self._detect_smoking_heuristic(frame, droi)

        return state
