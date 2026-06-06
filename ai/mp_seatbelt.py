"""
Emniyet kemeri tespiti — MediaPipe Pose + çapraz şerit (Canny/Hough) heuristiği.

NEDEN VAR
---------
Şartname madde 4.4 "emniyet kemeri" davranışı. COCO'da kemer sınıfı YOK ve henüz
fine-tune'lu model gelmedi (bkz. PROGRESS R2). Kemer takılıyken gövdeyi çapraz
kesen belirgin bir şerit görünür; bu modül onu *eğitimsiz* yakalar:

  1. MediaPipe Pose → omuz (11/12) ve kalça (23/24) landmark'ları → gövde ROI.
  2. Gövde ROI'sinde Canny kenar + olasılıksal Hough → çizgi parçaları.
  3. Omuzdan karşı kalçaya giden açıdaki (≈25°–65°) yeterince UZUN çizgi = kemer.

DÜRÜSTLÜK NOTU
--------------
Bu bir HEURISTIC'tir; desenli kıyafet/gölge yanlış pozitif, koyu kemer yanlış
negatif üretebilir. Bu yüzden:
  - Yalnız gövde NET görünürse çalışır (landmark visibility eşiği).
  - Ardışık-kare onayı (debounce) ile titreme süzülür.
  - "kemer yok" (no_seatbelt) muhafazakâr verilir (kanıt eksikse bayrak kalkmaz).
Kesin çözüm: `ai/training/` ile kemer sınıfı fine-tune. Bu modül o gelene kadar köprü.

TASARIM (tam kapsüllü — mp_cabin.py ile aynı desen)
---------------------------------------------------
Tek arayüz: SeatbeltDetector.detect(roi_bgr) -> SeatbeltSignal
MediaPipe/cv2 yoksa otomatik mock'a düşer ve ASLA bayrak üretmez (K4).
Tüm eşikler config/settings.py içinde (K3).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np

# MediaPipe Pose landmark indeksleri
_L_SHOULDER, _R_SHOULDER = 11, 12
_L_HIP, _R_HIP = 23, 24


@dataclass
class SeatbeltSignal:
    """Kemer tespitinin ham çıktısı (API kontratı DEĞİL — iç sinyal)."""
    torso_found: bool = False        # gövde (omuz+kalça) yeterli güvenle bulundu mu
    belt_on: bool = False            # çapraz kemer şeridi tespit edildi mi
    no_seatbelt: bool = False        # gövde var AMA kemer yok (debounce sonrası)
    score: float = 0.0               # 0-1 en iyi çizgi güveni


class SeatbeltDetector:
    def __init__(self, settings=None, mode: str = "auto"):
        if settings is None:
            from config.settings import get_settings
            settings = get_settings()
        self.s = settings
        self.mode = self._resolve(mode, settings)
        self._pose = None
        # Debounce: "kemer yok" kararı tek karelik gürültüyle verilmesin (muhafazakâr)
        n = max(1, int(getattr(settings, "seatbelt_persist_frames", 5)))
        self._belt_hist: Deque[int] = deque(maxlen=n)
        if self.mode == "real":
            self._init_pose()

    # --- Kurulum / mod ------------------------------------------------------

    @staticmethod
    def _resolve(mode: str, settings) -> str:
        mode = (mode or "auto").lower()
        if not getattr(settings, "seatbelt_enabled", True):
            return "mock"
        if mode in ("real", "mock"):
            return mode
        try:
            import mediapipe  # noqa: F401
            import cv2  # noqa: F401
            return "real"
        except Exception:
            return "mock"

    def _init_pose(self) -> None:
        try:
            import mediapipe as mp
            self._pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=1,             # 1 = denge (kemer için omuz/kalça yeterli isabet)
                enable_segmentation=False,
                min_detection_confidence=float(getattr(self.s, "seatbelt_pose_conf", 0.4)),
                min_tracking_confidence=0.4,
            )
        except Exception as e:
            print(f"[SeatbeltDetector] MediaPipe Pose başlatılamadı: {e}")
            self.mode = "mock"
            self._pose = None

    # --- Ana tespit ---------------------------------------------------------

    def detect(self, roi: Optional[np.ndarray]) -> SeatbeltSignal:
        """Sürücü gövde ROI'sinde kemer şeridini arar (ROI = sürücü crop, BGR)."""
        if self.mode == "mock" or self._pose is None or roi is None or roi.size == 0:
            return SeatbeltSignal()

        try:
            import cv2
            rh, rw = roi.shape[:2]
            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB) if roi.ndim == 3 else roi
            res = self._pose.process(rgb)
        except Exception:
            return SeatbeltSignal()

        if not res.pose_landmarks:
            self._belt_hist.append(1)  # gövde yok → "kemer var gibi" say (no_seatbelt tetiklenmesin)
            return SeatbeltSignal()

        lm = res.pose_landmarks.landmark
        min_vis = float(getattr(self.s, "seatbelt_min_visibility", 0.5))
        pts = {}
        for i in (_L_SHOULDER, _R_SHOULDER, _L_HIP, _R_HIP):
            p = lm[i]
            if p.visibility < min_vis:
                # Gövde net değil → karar verme (no_seatbelt muhafazakâr: bayrak yok)
                self._belt_hist.append(1)
                return SeatbeltSignal(torso_found=False)
            pts[i] = (p.x * rw, p.y * rh)

        # Gövde ROI: omuz-kalça kutusu + yanlara küçük pay (kemer ankrajları için)
        xs = [pts[i][0] for i in pts]
        ys = [pts[i][1] for i in pts]
        pad = 0.12 * (max(xs) - min(xs) + 1)
        tx1 = int(max(0, min(xs) - pad)); tx2 = int(min(rw, max(xs) + pad))
        ty1 = int(max(0, min(ys)));        ty2 = int(min(rh, max(ys)))
        if tx2 - tx1 < 12 or ty2 - ty1 < 12:
            self._belt_hist.append(1)
            return SeatbeltSignal(torso_found=False)

        torso = roi[ty1:ty2, tx1:tx2]
        belt_on, score = self._find_diagonal_strap(torso)

        # Debounce: kemer "var" sinyali biriktir; yokluk ardışık doğrulanınca no_seatbelt
        self._belt_hist.append(1 if belt_on else 0)
        need = self._belt_hist.maxlen or 1
        # Pencerede HİÇ kemer çizgisi görülmediyse → kemer yok (muhafazakâr)
        no_belt = (len(self._belt_hist) == need and sum(self._belt_hist) == 0)

        return SeatbeltSignal(
            torso_found=True, belt_on=belt_on,
            no_seatbelt=no_belt, score=round(score, 3),
        )

    def _find_diagonal_strap(self, torso: np.ndarray):
        """Gövde crop'unda omuz→karşı-kalça açısında uzun çizgi var mı (Canny+Hough)."""
        try:
            import cv2
            th, tw = torso.shape[:2]
            gray = cv2.cvtColor(torso, cv2.COLOR_BGR2GRAY) if torso.ndim == 3 else torso
            # Kontrast normalizasyonu (koyu kabin / parlak güneş ışığı dengelensin)
            gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
            lo = int(getattr(self.s, "seatbelt_canny_low", 50))
            hi = int(getattr(self.s, "seatbelt_canny_high", 150))
            edges = cv2.Canny(gray, lo, hi)

            torso_diag = math.hypot(tw, th)
            min_len = float(getattr(self.s, "seatbelt_min_line_ratio", 0.45)) * torso_diag
            min_ang = float(getattr(self.s, "seatbelt_min_angle_deg", 25))
            max_ang = float(getattr(self.s, "seatbelt_max_angle_deg", 65))

            lines = cv2.HoughLinesP(
                edges, rho=1, theta=np.pi / 180, threshold=40,
                minLineLength=int(min_len), maxLineGap=int(0.08 * torso_diag),
            )
            if lines is None:
                return False, 0.0

            best = 0.0
            for x1, y1, x2, y2 in lines[:, 0, :]:
                length = math.hypot(x2 - x1, y2 - y1)
                if length < min_len:
                    continue
                ang = abs(math.degrees(math.atan2(abs(y2 - y1), abs(x2 - x1) + 1e-6)))
                if min_ang <= ang <= max_ang:
                    # Uzunluğu gövde köşegenine oranla güven skoru (1.0'da doy)
                    best = max(best, min(1.0, length / torso_diag))
            return best > 0.0, best
        except Exception:
            return False, 0.0

    def close(self) -> None:
        try:
            if self._pose is not None:
                self._pose.close()
        except Exception:
            pass
