"""
Plaka takibi — araç track_id'sine bağlı kararlılık katmanı.

Neden var (kullanıcı isteği): "Plaka karede yoksa araç id'sine bağlı şekilde devam
etsin; saçma şeyleri plaka sanmasın." Plaka her karede net görünmez (uzak, eğik,
hareket bulanık). IOUTracker araçları zaten track_id ile takip ediyor; biz de plaka
sonucunu bu track_id'ye bağlarız:

  - Bir araç için ŞİMDİYE KADARKİ EN İYİ geçerli plaka okumasını sakla
    (öncelik: geçerli TR formatı > güven > keskinlik).
  - O karede plaka okunamazsa, aracın SON BİLİNEN plakasını döndür (id'ye bağlı süreklilik)
    → ekranda titremez, yanlış/boş kayda düşmez.
  - Araç sahneden çıkınca (ttl) durum temizlenir (bellek sızıntısı yok).

Saf Python — cv2/torch gerektirmez (K4 mock-first; testlenebilir).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

from ai.schema import BBox, PlateResult


@dataclass
class PlateTrackState:
    """Tek bir araç track'i için biriken plaka durumu."""
    text: Optional[str] = None
    confidence: float = 0.0
    valid_format: bool = False
    bbox: Optional[BBox] = None             # full-frame plaka kutusu (en iyi okumadan)
    pixel_width: Optional[float] = None
    sharpness: float = 0.0
    last_frame: int = 0                     # en son güncellendiği frame_id (ttl için)
    hits: int = 0                           # bu track'te kaç geçerli okuma görüldü


def _rank(valid: bool, conf: float, sharp: float) -> Tuple[int, float]:
    """Bir okumanın 'iyilik' sıralaması: önce geçerli format, sonra güven (+az keskinlik)."""
    return (1 if valid else 0, conf + 0.0005 * sharp)


class PlateTracker:
    """Araç track_id → en iyi plaka durumu. Pipeline her kritik karede update+resolve eder."""

    def __init__(self, ttl_frames: int = 45):
        # ttl_frames: araç bu kadar kare görünmezse durumu unut (50 fps'de ~1 sn).
        self._states: Dict[int, PlateTrackState] = {}
        self._ttl = ttl_frames

    def update(
        self,
        track_id: Optional[int],
        plate: PlateResult,
        bbox: Optional[BBox],
        sharpness: float,
        frame_id: int,
    ) -> None:
        """Bu karenin okumasını track'e işle — yalnız öncekinden DAHA İYİYSE üzerine yazar.

        Geçersiz/boş okuma mevcut en iyiyi EZMEZ (id'ye bağlı süreklilik). Sadece
        'görüldü' zamanını tazelemek için last_frame güncellenir.
        """
        if track_id is None:
            return
        st = self._states.get(track_id)
        if st is None:
            st = PlateTrackState()
            self._states[track_id] = st
        st.last_frame = frame_id

        if not plate or not plate.text:
            return  # bu karede okuma yok → eski en iyi korunur

        new_r = _rank(plate.valid_format, plate.confidence, sharpness)
        cur_r = _rank(st.valid_format, st.confidence, st.sharpness)
        if plate.valid_format:
            st.hits += 1
        if new_r >= cur_r:
            st.text = plate.text
            st.confidence = plate.confidence
            st.valid_format = plate.valid_format
            st.sharpness = sharpness
            if bbox is not None:
                st.bbox = bbox
                st.pixel_width = round(bbox.width, 1)

    def resolve(self, track_id: Optional[int]) -> Tuple[PlateResult, Optional[BBox], Optional[float]]:
        """Track için kararlı (en iyi) plaka sonucunu döndür. Yoksa boş PlateResult."""
        if track_id is None:
            return PlateResult(), None, None
        st = self._states.get(track_id)
        if st is None or not st.text:
            return PlateResult(), None, None
        return (
            PlateResult(text=st.text, confidence=round(st.confidence, 3),
                        valid_format=st.valid_format),
            st.bbox,
            st.pixel_width,
        )

    def prune(self, alive_ids: Set[int], frame_id: int) -> None:
        """Sahneden çıkmış / ttl aşmış track durumlarını sil."""
        dead = [
            tid for tid, st in self._states.items()
            if tid not in alive_ids and (frame_id - st.last_frame) > self._ttl
        ]
        for tid in dead:
            self._states.pop(tid, None)
