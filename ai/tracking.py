"""
Çoklu nesne takip altyapısı.

• Track       — tek araç geçmişi (foot_history, ts_history, …)
• KalmanSpeed1D — kare-başı hız tahminindeki titremeyi bastıran 1-D Kalman
• IOUTracker  — IOU tabanlı fallback (mock mod); external_ids parametresiyle
                ByteTrack / BoT-SORT gibi harici izleyicilerin ID'lerini de kabul eder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import deque


class KalmanSpeed1D:
    """1-D sabit-hız Kalman filtresi — kare-başı hız tahminindeki titremeyi bastırır.

    Durum x = düzgünleştirilmiş hız. Birim, beslenen ölçümün birimidir: metrik
    yol (MetricSpeedEstimator) m/s besler, sezgisel yol (pipeline) km/h besler.
    Filtre lineer olduğu ve kazanç dizisi yalnız (P₀, Q, R)'ye bağlı olduğu için
    düzgünleştirme oranı ölçekten BAĞIMSIZDIR — aynı Q/R her iki birimde de aynı
    yumuşatmayı verir (bkz. test_kalman_damps_sudden_change).
    Q: süreç gürültüsü (araç hızının ne kadar değişebildiği).
    R: ölçüm gürültüsü (anlık BEV hız tahmininin güvenilmezliği).
    P=200 başlangıcı → filtre ilk ölçüme hızlı yakınsıyor, sonra Q/R dengesine
    göre ne kadar güncelleneceğini belirliyor.
    """
    __slots__ = ("x", "P", "Q", "R", "_init")

    def __init__(self, Q: float = 3.0, R: float = 8.0):
        self.Q = Q
        self.R = R
        self.x = 0.0
        self.P = 200.0
        self._init = False

    def update(self, z: float) -> float:
        if not self._init:
            self.x = z
            self._init = True
            return z
        self.P += self.Q
        K = self.P / (self.P + self.R)
        self.x += K * (z - self.x)
        self.P *= (1.0 - K)
        return self.x


def iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    track_id: int
    bbox: Tuple[float, float, float, float]
    area_history: deque = field(default_factory=lambda: deque(maxlen=12))
    center_history: deque = field(default_factory=lambda: deque(maxlen=12))
    # Yer-temas noktası (bbox alt-orta piksel) geçmişi — aracın yere değdiği nokta.
    # Metrik hız ppm(y)/homografi yer düzlemi hesabı bu noktayı kullanır (§7.2).
    # maxlen=16 (>12): §12 derinliğe-uyarlı pencere uzaktaki araçta uzun baz isteyebilir.
    foot_history: deque = field(default_factory=lambda: deque(maxlen=16))
    # Her güncellemenin VİDEO ZAMAN ÇİZGİSİ damgası (s) — PTS/client_ts; yoksa None.
    # foot_history ile PARALEL (aynı maxlen); metrik hız için "gerçek Δt" buradan gelir.
    ts_history: deque = field(default_factory=lambda: deque(maxlen=16))
    misses: int = 0
    hits: int = 1

    def update(self, bbox: Tuple[float, float, float, float],
               ts: float | None = None) -> None:
        self.bbox = bbox
        x1, y1, x2, y2 = bbox
        self.area_history.append(max(0.0, x2 - x1) * max(0.0, y2 - y1))
        self.center_history.append(((x1 + x2) / 2, (y1 + y2) / 2))
        self.foot_history.append(((x1 + x2) / 2, y2))
        self.ts_history.append(ts)
        self.misses = 0
        self.hits += 1

    def dt_last(self) -> float | None:
        """Son iki güncelleme arasında YERDEKİ gerçek geçen süre (s).

        Karelerin nominal 1/fps aralığını DEĞİL, fiilen damgalanmış iki örnek
        arasındaki süreyi döndürür; böylece düşürülen kareler (track birkaç
        kare 'miss' olup sonra güncellendiğinde) doğru çok-kareli Δt verir.
        Zaman damgası yoksa (None) ya da süre artmıyorsa None döner.
        """
        if len(self.ts_history) < 2:
            return None
        t_prev, t_cur = self.ts_history[-2], self.ts_history[-1]
        if t_prev is None or t_cur is None:
            return None
        dt = t_cur - t_prev
        return dt if dt > 0 else None

    def area_growth_ratio(self) -> float:
        """Son ölçümün, birkaç kare önceye göre alan büyüme oranı (yaklaşma sinyali)."""
        if len(self.area_history) < 2:
            return 0.0
        prev = self.area_history[0]
        cur = self.area_history[-1]
        if prev <= 1e-6:
            return 0.0
        return (cur - prev) / prev

    def is_swerving(self, min_frames: int = 10, min_direction_changes: int = 2,
                    rapid_lateral_px: float = 350.0) -> bool:
        """
        Araç swerving yapıyor mu?
        İki kriter:
        1. Zigzag: son N karede en az 2 sol↔sağ yön değişimi
        2. Hızlı yanal hareket: son 15 karede >350px (1080p varsayımı) lateral kayma
        """
        if len(self.center_history) < min_frames:
            return False
        xs = [c[0] for c in self.center_history]

        # Kriter 2: hızlı yanal yer değiştirme (şerit değişimi / manevra)
        recent = xs[-15:] if len(xs) >= 15 else xs
        if (max(recent) - min(recent)) > rapid_lateral_px:
            return True

        x_range = max(xs) - min(xs)
        if x_range < 15:
            return False

        # Kriter 1: zigzag (yön değişim sayımı)
        smoothed = []
        for i in range(len(xs)):
            window = xs[max(0, i - 2): i + 1]
            smoothed.append(sum(window) / len(window))
        direction = 0
        changes = 0
        for i in range(1, len(smoothed)):
            dx = smoothed[i] - smoothed[i - 1]
            if abs(dx) < 2:
                continue
            new_dir = 1 if dx > 0 else -1
            if direction != 0 and new_dir != direction:
                changes += 1
            direction = new_dir
        return changes >= min_direction_changes


class IOUTracker:
    def __init__(self, iou_threshold: float = 0.3, max_misses: int = 8):
        self.iou_threshold = iou_threshold
        self.max_misses = max_misses
        self._next_id = 1
        self.tracks: Dict[int, Track] = {}

    def update(self, boxes: List[Tuple[float, float, float, float]],
               ts: float | None = None,
               external_ids: Optional[List[Optional[int]]] = None) -> List[int]:
        """boxes -> her kutuya karşılık gelen track_id listesi (sırayı korur).

        ts: bu karenin video-zaman çizgisi damgası (s, PTS/client_ts).
        external_ids: ByteTrack / BoT-SORT gibi harici bir izleyiciden gelen
            ID listesi (boxes ile aynı uzunlukta). None elemanlar IOU ile atanır.
            Tüm liste None ise klasik IOU eşleştirme çalışır.
        """
        if external_ids is not None and any(eid is not None for eid in external_ids):
            return self._update_external(boxes, ts, external_ids)

        assigned: Dict[int, int] = {}      # box_index -> track_id
        used_tracks = set()

        # Greedy IOU eşleştirme
        pairs = []
        for bi, box in enumerate(boxes):
            for tid, tr in self.tracks.items():
                pairs.append((iou(box, tr.bbox), bi, tid))
        pairs.sort(reverse=True)
        for score, bi, tid in pairs:
            if score < self.iou_threshold:
                break
            if bi in assigned or tid in used_tracks:
                continue
            assigned[bi] = tid
            used_tracks.add(tid)
            self.tracks[tid].update(boxes[bi], ts=ts)

        # Eşleşmeyen kutulara yeni track
        for bi, box in enumerate(boxes):
            if bi not in assigned:
                tid = self._next_id
                self._next_id += 1
                tr = Track(track_id=tid, bbox=box)
                tr.update(box, ts=ts)
                self.tracks[tid] = tr
                assigned[bi] = tid

        # Eşleşmeyen track'leri yaşlandır / sil
        for tid in list(self.tracks.keys()):
            if tid not in used_tracks and tid not in assigned.values():
                self.tracks[tid].misses += 1
                if self.tracks[tid].misses > self.max_misses:
                    del self.tracks[tid]

        return [assigned[bi] for bi in range(len(boxes))]

    def _update_external(self, boxes: List[Tuple[float, float, float, float]],
                         ts: float | None,
                         external_ids: List[Optional[int]]) -> List[int]:
        """ByteTrack / BoT-SORT ID'leriyle Track geçmişini günceller.

        Harici izleyici IOU eşleştirmesini zaten yaptı; biz sadece Track nesnelerini
        (foot_history, ts_history, …) koruyup hız/swerving hesabı için kullanırız.
        ID çakışmasını önlemek için _next_id, en yüksek harici ID'nin üstüne güncellenir.
        """
        used_tracks: set = set()
        result: List[int] = []

        for bbox, eid in zip(boxes, external_ids):
            if eid is None:
                tid = self._next_id
                self._next_id += 1
            else:
                tid = eid
            if tid not in self.tracks:
                t = Track(track_id=tid, bbox=bbox)
                self.tracks[tid] = t
            self.tracks[tid].update(bbox, ts=ts)
            used_tracks.add(tid)
            result.append(tid)

        # _next_id'yi harici ID'lerin üstüne çek (çakışma önleme)
        if used_tracks:
            self._next_id = max(self._next_id, max(used_tracks) + 1)

        # Görülmeyen track'leri yaşlandır / sil
        for tid in list(self.tracks.keys()):
            if tid not in used_tracks:
                self.tracks[tid].misses += 1
                if self.tracks[tid].misses > self.max_misses:
                    del self.tracks[tid]

        return result

    def get(self, track_id: int) -> Track | None:
        return self.tracks.get(track_id)
