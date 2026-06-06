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
    bbox: Optional[BBox] = None             # full-frame plaka kutusu (EMA düzgünleştirilmiş)
    pixel_width: Optional[float] = None
    sharpness: float = 0.0
    last_frame: int = 0                     # en son görüldüğü frame_id (ttl için)
    hits: int = 0                           # bu track'te kaç geçerli okuma görüldü
    # Son bilinen bbox — plaka görünmese de son pozisyonu görselleştirme için saklar.
    last_seen_bbox: Optional[BBox] = None
    last_seen_frame: int = 0


def _rank(valid: bool, conf: float, sharp: float) -> Tuple[int, float]:
    """Bir okumanın 'iyilik' sıralaması: önce geçerli format, sonra güven (+az keskinlik)."""
    return (1 if valid else 0, conf + 0.0005 * sharp)


# EMA katsayısı: 0.35 → yeni ölçüm %35, eski konum %65 ağırlık (titreme önleme).
_BBOX_EMA = 0.35


def _ema_bbox(old: Optional[BBox], new: BBox) -> BBox:
    """Plaka bbox konumunu EMA ile düzgünleştirir — ani sıçramaları azaltır."""
    if old is None:
        return new
    a = _BBOX_EMA
    return BBox(
        x1=a * new.x1 + (1 - a) * old.x1,
        y1=a * new.y1 + (1 - a) * old.y1,
        x2=a * new.x2 + (1 - a) * old.x2,
        y2=a * new.y2 + (1 - a) * old.y2,
    )


class PlateTracker:
    """Araç track_id → en iyi plaka durumu. Pipeline her kritik karede update+resolve eder."""

    def __init__(self, ttl_frames: int = 75):
        # ttl_frames: araç bu kadar kare görünmezse durumu unut (50 fps'de ~1.5 sn).
        # 45→75: kısa gizlenme/geçiş anında plakayı yitirme riski azalır.
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
        Bbox her tespitte EMA ile güncellenir (OCR başarısız olsa bile).
        """
        if track_id is None:
            return
        st = self._states.get(track_id)
        if st is None:
            st = PlateTrackState()
            self._states[track_id] = st
        st.last_frame = frame_id

        # Plaka bbox'ı tespit edildiğinde her zaman güncelle (OCR sonucundan bağımsız).
        # Bu sayede plaka konumu sürekli takip edilir; son bilinen pozisyon görselleştirilir.
        if bbox is not None:
            st.last_seen_bbox = _ema_bbox(st.last_seen_bbox, bbox)
            st.last_seen_frame = frame_id

        if not plate or not plate.text:
            return  # bu karede OCR okuma yok → metin en iyisi korunur

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
                st.bbox = _ema_bbox(st.bbox, bbox)
                st.pixel_width = round(st.bbox.width, 1)

    def resolve(self, track_id: Optional[int]) -> Tuple[PlateResult, Optional[BBox], Optional[float]]:
        """Track için kararlı (en iyi) plaka sonucunu döndür. Yoksa boş PlateResult.

        Bbox olarak: en iyi okumaya ait EMA-düzgünleştirilmiş kutu tercih edilir.
        Metin yoksa son görülen bbox döndürülür (görselleştirmede kutu kaybolmaz).
        """
        if track_id is None:
            return PlateResult(), None, None
        st = self._states.get(track_id)
        if st is None:
            return PlateResult(), None, None
        plate_result = (
            PlateResult(text=st.text, confidence=round(st.confidence, 3),
                        valid_format=st.valid_format)
            if st.text else PlateResult()
        )
        bbox = st.bbox if st.bbox is not None else st.last_seen_bbox
        pw = st.pixel_width if st.pixel_width is not None else (
            round(bbox.width, 1) if bbox is not None else None
        )
        return plate_result, bbox, pw

    def prune(self, alive_ids: Set[int], frame_id: int) -> None:
        """Sahneden çıkmış / ttl aşmış track durumlarını sil."""
        dead = [
            tid for tid, st in self._states.items()
            if tid not in alive_ids and (frame_id - st.last_frame) > self._ttl
        ]
        for tid in dead:
            self._states.pop(tid, None)
