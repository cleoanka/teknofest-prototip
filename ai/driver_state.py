"""
Sürücü durumu — yorgunluk (EAR/PERCLOS), telefon, sigara, kemer, kulaklık.

- Yorgunluk: MediaPipe Face Mesh ile göz landmark'larından EAR; zaman penceresinde
  PERCLOS. Kütüphane yoksa mock skor (kare içeriğinden deterministik).
- Telefon/sigara/kemer/kulaklık: detector çıktısındaki nesnelerin sürücü ROI'siyle
  kesişiminden kural-tabanlı çıkarım. (Sigara/kemer/kulaklık fine-tune sınıfları;
  mevcut COCO modelinde yoksa mock/kural ile üretilir.)
"""
from __future__ import annotations

from collections import deque
from typing import List, Optional

import numpy as np

from ai.schema import Detection, DriverState, BBox

EAR_THRESHOLD = 0.21
PERCLOS_WINDOW = 30       # ~1 sn @30fps
PERCLOS_FATIGUE = 0.40    # %40 üstü -> yorgun

# MediaPipe Face Mesh göz landmark indeksleri
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]


def _ear(pts) -> float:
    # pts: 6x2 (p1..p6) ; EAR = (|p2-p6| + |p3-p5|) / (2|p1-p4|)
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
                    static_image_mode=False, max_num_faces=1, refine_landmarks=True,
                    min_detection_confidence=0.5,
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

    def _fatigue_real(self, frame: np.ndarray) -> tuple[Optional[float], Optional[float], bool]:
        try:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if frame.ndim == 3 else frame
        except Exception:
            rgb = frame
        h, w = frame.shape[:2]
        res = self._mesh.process(rgb)
        if not res.multi_face_landmarks:
            self._eye_closed.append(0)
            return None, self._perclos(), False
        lm = res.multi_face_landmarks[0].landmark
        def pick(idx):
            return [(lm[i].x * w, lm[i].y * h) for i in idx]
        ear = (_ear(pick(_LEFT_EYE)) + _ear(pick(_RIGHT_EYE))) / 2.0
        self._eye_closed.append(1 if ear < EAR_THRESHOLD else 0)
        perclos = self._perclos()
        return round(ear, 3), perclos, perclos > PERCLOS_FATIGUE

    def _perclos(self) -> float:
        if not self._eye_closed:
            return 0.0
        return round(sum(self._eye_closed) / len(self._eye_closed), 3)

    def _fatigue_mock(self, frame: np.ndarray) -> tuple[Optional[float], Optional[float], bool]:
        # Deterministik: parlaklık düşükse "göz kapalı" varsay (demo amaçlı)
        b = float(frame.mean()) if frame is not None and frame.size else 128.0
        ear = round(0.30 - (1.0 - min(b, 255) / 255.0) * 0.18, 3)
        self._eye_closed.append(1 if ear < EAR_THRESHOLD else 0)
        perclos = self._perclos()
        return ear, perclos, perclos > PERCLOS_FATIGUE

    @staticmethod
    def _driver_roi(detections: List[Detection], frame_shape) -> Optional[BBox]:
        """Araç kutusunun sol-üst kabin bölgesi (sürücü) yaklaşık ROI'si."""
        veh = [d for d in detections if d.label == "vehicle"]
        if not veh:
            return None
        v = max(veh, key=lambda d: d.bbox.area).bbox
        w = v.x2 - v.x1
        h = v.y2 - v.y1
        return BBox(x1=v.x1 + 0.05 * w, y1=v.y1 + 0.10 * h,
                    x2=v.x1 + 0.55 * w, y2=v.y1 + 0.75 * h)

    @staticmethod
    def _overlaps(a: BBox, b: BBox) -> bool:
        return not (a.x2 < b.x1 or a.x1 > b.x2 or a.y2 < b.y1 or a.y1 > b.y2)

    def assess(self, frame: np.ndarray, detections: List[Detection], profile: str) -> DriverState:
        state = DriverState()
        # Yorgunluk yalnızca kritik profilde (yüksek çözünürlük) güvenilir
        if profile == "critical" and frame is not None and frame.size:
            ear, perclos, fatigue = (self._fatigue_real if self.mode == "real" else self._fatigue_mock)(frame)
            state.ear, state.perclos, state.fatigue = ear, perclos, fatigue

        roi = self._driver_roi(detections, frame.shape if frame is not None else (0, 0))
        if roi is not None:
            for d in detections:
                if d.label == "phone" and self._overlaps(roi, d.bbox):
                    state.phone_use = True
                elif d.label == "cigarette" and self._overlaps(roi, d.bbox):
                    state.smoking = True
                elif d.label == "headphone" and self._overlaps(roi, d.bbox):
                    state.headphone = True
            has_seatbelt = any(d.label == "seatbelt" and self._overlaps(roi, d.bbox)
                               for d in detections)
            # COCO ön-eğitimli modelde seatbelt sınıfı yok; yalnızca fine-tune
            # modelinde has_seatbelt=True gelebilir. Aksi hâlde her zaman FP üretir.
            state.no_seatbelt = bool(has_seatbelt is True and False)  # fine-tune gelene kadar devre dışı
        return state
