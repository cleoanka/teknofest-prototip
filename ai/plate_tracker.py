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
  - Bbox yokken velocity ile extrapolasyon: plakanın hareket yönü tahmin edilir,
    görselleştirmede kutu kaybı azalır.
  - 4 perspektif köşesi EMA ile takip edilir (yamuk plaka görselleştirmesi için).
  - Araç sahneden çıkınca (ttl) durum temizlenir (bellek sızıntısı yok).

Saf Python — cv2/torch gerektirmez (K4 mock-first; testlenebilir).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

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
    # Son bilinen bbox (OCR başarısız olsa bile) — görselleştirme için
    last_seen_bbox: Optional[BBox] = None
    last_seen_frame: int = 0
    # Velocity (px/frame, EMA) — bbox yokken extrapolasyon için
    vel_x: float = 0.0
    vel_y: float = 0.0
    # 4 perspektif köşesi [[x,y]×4] — yamuk plaka görselleştirmesi
    corners: Optional[List[List[float]]] = None
    # Frekans oylama: text → [görülme_sayısı, en_yüksek_güven]
    # "En iyi tek okuma" yerine en çok görülen geçerli metni döndürmek için.
    # 3↔0 gibi OCR karmaşasında doğru metin çoğunluk kazanır.
    text_votes: "dict[str, list]" = field(default_factory=dict)


def _rank(valid: bool, conf: float, sharp: float) -> Tuple[int, float]:
    """Bir okumanın 'iyilik' sıralaması: önce geçerli format, sonra güven (+az keskinlik)."""
    return (1 if valid else 0, conf + 0.0005 * sharp)


# EMA katsayıları
_BBOX_EMA = 0.35     # bbox konumu: yeni %35, eski %65
_VEL_EMA = 0.40      # velocity: yeni %40, eski %60
_CORNER_EMA = 0.35   # köşe konumu: bbox ile aynı ağırlık


def _ema_bbox(old: Optional[BBox], new: BBox) -> BBox:
    """Plaka bbox konumunu EMA ile düzgünleştirir."""
    if old is None:
        return new
    a = _BBOX_EMA
    return BBox(
        x1=a * new.x1 + (1 - a) * old.x1,
        y1=a * new.y1 + (1 - a) * old.y1,
        x2=a * new.x2 + (1 - a) * old.x2,
        y2=a * new.y2 + (1 - a) * old.y2,
    )


def _ema_corners(
    old: Optional[List[List[float]]],
    new: np.ndarray,
) -> List[List[float]]:
    """4 köşe konumunu EMA ile düzgünleştirir."""
    new_list = new.tolist() if hasattr(new, "tolist") else new
    if old is None or len(old) != 4:
        return new_list
    a = _CORNER_EMA
    return [
        [a * n[0] + (1 - a) * o[0], a * n[1] + (1 - a) * o[1]]
        for o, n in zip(old, new_list)
    ]


class PlateTracker:
    """Araç track_id → en iyi plaka durumu. Pipeline her kritik karede update+resolve eder."""

    def __init__(self, ttl_frames: int = 75):
        # 50 fps'de ~1.5 sn; kısa gizlenme/geçiş anında plakayı yitirme riski azalır.
        self._states: Dict[int, PlateTrackState] = {}
        self._ttl = ttl_frames

    def update(
        self,
        track_id: Optional[int],
        plate: PlateResult,
        bbox: Optional[BBox],
        sharpness: float,
        frame_id: int,
        corners: Optional[List[List[float]]] = None,
    ) -> None:
        """Bu karenin okumasını track'e işle — yalnız öncekinden DAHA İYİYSE üzerine yazar.

        Boş okuma mevcut en iyiyi EZMEZ. Bbox her tespitte EMA ile güncellenir.
        Velocity, ardışık bbox pozisyonlarından kademeli olarak birikir.
        """
        if track_id is None:
            return
        st = self._states.get(track_id)
        if st is None:
            st = PlateTrackState()
            self._states[track_id] = st
        st.last_frame = frame_id

        # Bbox görüldüğünde velocity ve last_seen'i güncelle
        if bbox is not None:
            if st.last_seen_bbox is not None and frame_id > st.last_seen_frame > 0:
                dt = max(1, frame_id - st.last_seen_frame)
                new_vx = (bbox.cx - st.last_seen_bbox.cx) / dt
                new_vy = (bbox.cy - st.last_seen_bbox.cy) / dt
                st.vel_x = _VEL_EMA * new_vx + (1 - _VEL_EMA) * st.vel_x
                st.vel_y = _VEL_EMA * new_vy + (1 - _VEL_EMA) * st.vel_y
            st.last_seen_bbox = _ema_bbox(st.last_seen_bbox, bbox)
            st.last_seen_frame = frame_id

        # 4 perspektif köşesi EMA
        if corners is not None and len(corners) == 4:
            import numpy as _np
            st.corners = _ema_corners(st.corners, _np.array(corners))

        if not plate or not plate.text:
            return

        new_r = _rank(plate.valid_format, plate.confidence, sharpness)
        cur_r = _rank(st.valid_format, st.confidence, st.sharpness)
        if plate.valid_format:
            st.hits += 1
            # Frekans oylama: geçerli formatli okumalari say.
            entry = st.text_votes.setdefault(plate.text, [0, 0.0])
            entry[0] += 1
            entry[1] = max(entry[1], plate.confidence)
        if new_r >= cur_r:
            st.text = plate.text
            st.confidence = plate.confidence
            st.valid_format = plate.valid_format
            st.sharpness = sharpness
            if bbox is not None:
                st.bbox = _ema_bbox(st.bbox, bbox)
                st.pixel_width = round(st.bbox.width, 1)

    def resolve(
        self,
        track_id: Optional[int],
        frame_id: int = -1,
    ) -> Tuple[PlateResult, Optional[BBox], Optional[float], Optional[List[List[float]]]]:
        """Track için kararlı (en iyi) plaka sonucunu döndür.

        frame_id verilirse velocity ile extrapolasyon yapılır (bbox görünmüyorken
        son bilinen konumu hareket yönüne göre taşır, en fazla 5 frame).

        Dönüş: (PlateResult, bbox, pixel_width, corners_4x2).
        """
        if track_id is None:
            return PlateResult(), None, None, None
        st = self._states.get(track_id)
        if st is None:
            return PlateResult(), None, None, None

        # Frekans kazananı: en çok görülen geçerli metin (tie-break: güven).
        # En iyi tek okuma yerine bu kullan — 3↔0 gibi karmaşada çoğunluk doğruyu seçer.
        if st.text_votes:
            winner = max(st.text_votes, key=lambda k: (st.text_votes[k][0], st.text_votes[k][1]))
            best_conf = st.text_votes[winner][1]
            plate_result = PlateResult(text=winner, confidence=round(best_conf, 3), valid_format=True)
        elif st.text:
            plate_result = PlateResult(text=st.text, confidence=round(st.confidence, 3),
                                       valid_format=st.valid_format)
        else:
            plate_result = PlateResult()

        # Bbox: en iyi okumaya ait kutu, yoksa son bilinen (velocity ile extrapolasyon)
        bbox = st.bbox if st.bbox is not None else st.last_seen_bbox
        if bbox is None:
            return plate_result, None, None, st.corners

        # Velocity extrapolasyon: son görülmeden bu yana geçen frame sayısı
        if frame_id > 0 and st.last_seen_frame > 0:
            dt = frame_id - st.last_seen_frame
            if 0 < dt <= 5 and (abs(st.vel_x) > 0.3 or abs(st.vel_y) > 0.3):
                dx = st.vel_x * min(dt, 5)
                dy = st.vel_y * min(dt, 5)
                bbox = BBox(
                    x1=bbox.x1 + dx, y1=bbox.y1 + dy,
                    x2=bbox.x2 + dx, y2=bbox.y2 + dy,
                )

        pw = st.pixel_width if st.pixel_width is not None else round(bbox.width, 1)
        return plate_result, bbox, pw, st.corners

    def prune(self, alive_ids: Set[int], frame_id: int) -> None:
        """Sahneden çıkmış / ttl aşmış track durumlarını sil."""
        dead = [
            tid for tid, st in self._states.items()
            if tid not in alive_ids and (frame_id - st.last_frame) > self._ttl
        ]
        for tid in dead:
            self._states.pop(tid, None)
