"""
Kabin davranış analizi — MediaPipe Hands ile el-yüz yakınlık tespiti.

NEDEN VAR
---------
Şartname madde 4.4 "yol güvenliğini tehdit eden sürücü davranışları": telefon
kullanımı, sigara, kulaklık. Bu nesneler COCO'da ya yok (sigara/kulaklık) ya da
küçük/elle kapalı olduğu için YOLO tarafından sık kaçırılır. MediaPipe Hands
21 noktalı el iskeleti çıkararak nesneyi *görmeden* davranışı yakalar:

  - El parmak ucu KULAĞA yakın  -> telefonla konuşma / kulaklık takma
  - El parmak ucu AĞIZA yakın   -> sigara içme / yeme-içme

Bu modül YOLO tespitini "değiştirmez", onu GÜÇLENDİRİR (sensör füzyonu):
driver_state.py içinde MediaPipe sinyali ile YOLO sinyali VEYA'lanır → recall artar.

TASARIM (Kişi-2 OCR modülündeki gibi tam kapsüllü)
--------------------------------------------------
Diğer modüllerle tek arayüz:  CabinAnalyzer.analyze(roi, mouth_xy, ear_xys) -> CabinSignals
MediaPipe yoksa otomatik mock'a düşer (K4) ve ASLA sahte sinyal üretmez (boş döner).
Tüm eşikler config/settings.py içinde (K3) — burada hardcode yok.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import numpy as np

# MediaPipe Hands landmark indeksleri (parmak uçları + bilek)
# Parmak uçları davranış için en bilgilendirici noktalar (sigara/telefon parmakla tutulur).
_FINGERTIPS = [4, 8, 12, 16, 20]   # başparmak, işaret, orta, yüzük, serçe ucu
_WRIST = 0


@dataclass
class CabinSignals:
    """MediaPipe el analizinin ham çıktısı (API kontratı DEĞİL — iç sinyal)."""
    hands_detected: int = 0          # tespit edilen el sayısı (0-2)
    hand_near_ear: bool = False      # el kulağa yakın → telefon/kulaklık şüphesi
    hand_near_mouth: bool = False    # el ağıza yakın → sigara şüphesi
    ear_score: float = 0.0           # 0-1 yakınlık güveni (kalmanvari debounce öncesi)
    mouth_score: float = 0.0


class CabinAnalyzer:
    """
    Sürücü ROI'sinde el iskeletini çıkarıp el-yüz yakınlığını ölçer.

    mode:
      real → MediaPipe Hands yüklü, gerçek analiz
      mock → kütüphane yok / kapalı; her zaman boş CabinSignals döner (sahte üretmez)
    """

    def __init__(self, settings=None, mode: str = "auto"):
        # Eşikler tek noktadan (K3). settings verilmezse global ayarları çek.
        if settings is None:
            from config.settings import get_settings
            settings = get_settings()
        self.s = settings

        self.mode = self._resolve(mode, settings)
        self._hands = None

        # Gürültü filtresi: tek karelik yanlış pozitifi engellemek için ardışık-kare
        # onayı (debounce). qod_consecutive_required mantığıyla aynı felsefe.
        n = max(1, int(getattr(settings, "mp_cabin_persist_frames", 3)))
        self._ear_hist: Deque[int] = deque(maxlen=n)
        self._mouth_hist: Deque[int] = deque(maxlen=n)

        if self.mode == "real":
            self._init_hands()

    # --- Kurulum / mod çözümleme --------------------------------------------

    @staticmethod
    def _resolve(mode: str, settings) -> str:
        mode = (mode or "auto").lower()
        # Config ile tamamen kapatılabilsin (FPS düşükse devre dışı bırakmak için)
        if not getattr(settings, "mp_hands_enabled", True):
            return "mock"
        if mode in ("real", "mock"):
            return mode
        try:
            import mediapipe  # noqa: F401
            return "real"
        except Exception:
            return "mock"

    def _init_hands(self) -> None:
        try:
            import mediapipe as mp
            self._hands = mp.solutions.hands.Hands(
                static_image_mode=False,        # video akışı → izleme modu daha hızlı
                max_num_hands=2,                # sürücü iki eli (direksiyon + telefon)
                model_complexity=0,             # 0 = hızlı (gerçek-zaman kabin içi yeterli)
                min_detection_confidence=float(getattr(self.s, "mp_hand_detect_conf", 0.4)),
                min_tracking_confidence=0.4,
            )
        except Exception as e:
            print(f"[CabinAnalyzer] MediaPipe Hands başlatılamadı: {e}")
            self.mode = "mock"
            self._hands = None

    # --- Yardımcılar ---------------------------------------------------------

    @staticmethod
    def _min_dist_to(point: Tuple[float, float], tips_px: List[Tuple[float, float]]) -> float:
        """Bir referans noktasına (ağız/kulak) en yakın parmak ucu mesafesi (piksel)."""
        if not tips_px:
            return float("inf")
        px, py = point
        return min(((tx - px) ** 2 + (ty - py) ** 2) ** 0.5 for tx, ty in tips_px)

    # --- Ana analiz ----------------------------------------------------------

    def analyze(
        self,
        roi: Optional[np.ndarray],
        mouth_xy: Optional[Tuple[float, float]] = None,
        ear_xys: Optional[List[Tuple[float, float]]] = None,
        face_width: Optional[float] = None,
    ) -> CabinSignals:
        """
        Sürücü ROI crop'unda elleri bulup ağız/kulak yakınlığını döndürür.

        Parametreler ROI piksel uzayındadır (driver_state crop'u ile aynı):
          mouth_xy   : yüz mesh'inden ağız merkezi (None → ağız analizi atlanır)
          ear_xys    : [(sol_kulak), (sağ_kulak)] (None → kulak analizi atlanır)
          face_width : yüz genişliği (px) — mesafe eşiğini yüz ölçeğine göre normalize eder
                       (kameraya yakın/uzak sürücüde tutarlı kalsın diye)
        """
        if self.mode == "mock" or self._hands is None or roi is None or roi.size == 0:
            # Mock: sahte sinyal yok. Geçmişi de sıfırlamayalım ki gerçek moda
            # geçişte tutarlı kalsın; sadece boş sonuç dönüyoruz.
            return CabinSignals()

        try:
            import cv2
            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB) if roi.ndim == 3 else roi
            res = self._hands.process(rgb)
        except Exception:
            return CabinSignals()

        if not res.multi_hand_landmarks:
            self._ear_hist.append(0)
            self._mouth_hist.append(0)
            return CabinSignals(hands_detected=0)

        rh, rw = roi.shape[:2]
        # Tüm ellerin parmak uçlarını ROI piksel koordinatına çevir
        tips_px: List[Tuple[float, float]] = []
        for hand in res.multi_hand_landmarks:
            for idx in _FINGERTIPS:
                lm = hand.landmark[idx]
                tips_px.append((lm.x * rw, lm.y * rh))

        # Yakınlık eşiği: yüz genişliğine oranlı (ölçek-bağımsız). Yüz yoksa ROI
        # genişliğinin kabaca yarısını referans al.
        ref = float(face_width) if face_width and face_width > 1 else rw * 0.5
        ear_thr = ref * float(getattr(self.s, "mp_hand_near_ear_ratio", 0.9))
        mouth_thr = ref * float(getattr(self.s, "mp_hand_near_mouth_ratio", 0.7))

        ear_score = 0.0
        mouth_score = 0.0

        if ear_xys:
            d_ear = min(self._min_dist_to(e, tips_px) for e in ear_xys if e is not None) \
                if any(e is not None for e in ear_xys) else float("inf")
            if d_ear < ear_thr:
                # Yakınlaştıkça 0→1 artan güven (eşikte 0, temasta ~1)
                ear_score = max(0.0, 1.0 - d_ear / ear_thr)

        if mouth_xy is not None:
            d_mouth = self._min_dist_to(mouth_xy, tips_px)
            if d_mouth < mouth_thr:
                mouth_score = max(0.0, 1.0 - d_mouth / mouth_thr)

        # Debounce: ardışık-kare onayı (anlık titremeyi süzer)
        self._ear_hist.append(1 if ear_score > 0 else 0)
        self._mouth_hist.append(1 if mouth_score > 0 else 0)
        need = self._ear_hist.maxlen or 1
        ear_confirmed = sum(self._ear_hist) >= need
        mouth_confirmed = sum(self._mouth_hist) >= need

        return CabinSignals(
            hands_detected=len(res.multi_hand_landmarks),
            hand_near_ear=ear_confirmed,
            hand_near_mouth=mouth_confirmed,
            ear_score=round(ear_score, 3),
            mouth_score=round(mouth_score, 3),
        )

    def close(self) -> None:
        """MediaPipe kaynaklarını serbest bırak (sunucu kapanışında)."""
        try:
            if self._hands is not None:
                self._hands.close()
        except Exception:
            pass
