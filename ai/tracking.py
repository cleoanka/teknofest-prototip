"""
Hafif IOU tabanlı çoklu nesne takipçisi (ByteTrack-lite).

Amaç: araçlara kalıcı track_id atamak ve bbox alan geçmişini tutmak
(QoD tetik koşulu A — "yaklaşma/bbox büyümesi" ve hız tahmini için gerekli).
Harici bağımlılık yok; gerçek sistemde ByteTrack ile değiştirilebilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from collections import deque


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
    misses: int = 0
    hits: int = 1

    def update(self, bbox: Tuple[float, float, float, float]) -> None:
        self.bbox = bbox
        x1, y1, x2, y2 = bbox
        self.area_history.append(max(0.0, x2 - x1) * max(0.0, y2 - y1))
        self.center_history.append(((x1 + x2) / 2, (y1 + y2) / 2))
        self.misses = 0
        self.hits += 1

    def area_growth_ratio(self) -> float:
        """Son ölçümün, birkaç kare önceye göre alan büyüme oranı (yaklaşma sinyali)."""
        if len(self.area_history) < 2:
            return 0.0
        prev = self.area_history[0]
        cur = self.area_history[-1]
        if prev <= 1e-6:
            return 0.0
        return (cur - prev) / prev


class IOUTracker:
    def __init__(self, iou_threshold: float = 0.3, max_misses: int = 8):
        self.iou_threshold = iou_threshold
        self.max_misses = max_misses
        self._next_id = 1
        self.tracks: Dict[int, Track] = {}

    def update(self, boxes: List[Tuple[float, float, float, float]]) -> List[int]:
        """boxes -> her kutuya karşılık gelen track_id listesi (sırayı korur)."""
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
            self.tracks[tid].update(boxes[bi])

        # Eşleşmeyen kutulara yeni track
        for bi, box in enumerate(boxes):
            if bi not in assigned:
                tid = self._next_id
                self._next_id += 1
                tr = Track(track_id=tid, bbox=box)
                tr.update(box)
                self.tracks[tid] = tr
                assigned[bi] = tid

        # Eşleşmeyen track'leri yaşlandır / sil
        for tid in list(self.tracks.keys()):
            if tid not in used_tracks and tid not in assigned.values():
                self.tracks[tid].misses += 1
                if self.tracks[tid].misses > self.max_misses:
                    del self.tracks[tid]

        return [assigned[bi] for bi in range(len(boxes))]

    def get(self, track_id: int) -> Track | None:
        return self.tracks.get(track_id)
