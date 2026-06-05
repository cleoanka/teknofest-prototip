"""
Akıllı QoD Tetik Motoru (ÖTR Katkı 1).

500 ms değerlendirme döngüsünde 5 koşul kontrol edilir; iki ardışık pozitifte
yüksek bant (QoD) talep edilir. Bu, şartnamenin "yalnızca ihtiyaç varken bant
genişliğinin yükseltilmesi" (%40 ağırlık) gereksinimini doğrudan karşılar.

Koşullar:
  A — bbox alan büyümesi > eşik       (araç hızla yaklaşıyor)
  B — araç tespit güveni < eşik       (hafif model belirsiz)
  C — plaka ROI var ama OCR güveni düşük
  D — araç ROI çizgisini geçti        (okuma menziline girdi)
  E — araç içi nesne sınıfı sınır olasılıkta (0.4-0.6)

Bırakma: güven > release_conf  VEYA  oturum süresi doldu  VEYA  araç ROI dışında.

Bu modül SAF mantıktır (ağ çağrısı yok) → kolay test edilir. Gerçek bant
değişimini mock CAMARA QoD API (backend/camara/qod.py) yapar.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from config.settings import get_settings


@dataclass
class TriggerContext:
    bbox_growth: float = 0.0
    vehicle_present: bool = False
    vehicle_conf: float = 0.0
    vehicle_norm_y2: float = 0.0          # araç alt kenarının normalize konumu (0-1)
    plate_roi_present: bool = False
    plate_ocr_conf: float = 0.0
    ambiguous_object_confs: List[float] = field(default_factory=list)


@dataclass
class TriggerDecision:
    should_be_critical: bool
    reasons: List[str] = field(default_factory=list)
    fired_this_cycle: bool = False        # bu döngüde Normal->Kritik geçiş tetiklendi mi
    released_this_cycle: bool = False     # bu döngüde Kritik->Normal bırakma oldu mu

    @property
    def reason_text(self) -> Optional[str]:
        return "|".join(self.reasons) if self.reasons else None


class QoDTriggerEngine:
    def __init__(self, settings=None):
        self.s = settings or get_settings()
        self._consecutive = 0
        self.is_critical = False
        self._session_age_s = 0.0

    # ── koşul değerlendirmesi ────────────────────────────────────────────────
    def _conditions(self, ctx: TriggerContext) -> List[str]:
        s = self.s
        reasons = []
        if ctx.bbox_growth > s.qod_bbox_growth_threshold:
            reasons.append("A:yaklasma")
        if ctx.vehicle_present and ctx.vehicle_conf < s.qod_low_conf_threshold:
            reasons.append("B:dusuk_guven")
        if ctx.plate_roi_present and ctx.plate_ocr_conf < s.qod_ocr_conf_threshold:
            reasons.append("C:plaka_okunamadi")
        if ctx.vehicle_present and ctx.vehicle_norm_y2 >= s.qod_roi_line:
            reasons.append("D:roi_girisi")
        if any(s.qod_ambiguous_low <= c <= s.qod_ambiguous_high
               for c in ctx.ambiguous_object_confs):
            reasons.append("E:sinir_olasilik")
        return reasons

    def evaluate(self, ctx: TriggerContext, dt_s: float = 0.5) -> TriggerDecision:
        s = self.s
        reasons = self._conditions(ctx)
        positive = len(reasons) > 0

        decision = TriggerDecision(should_be_critical=self.is_critical, reasons=reasons)

        if not self.is_critical:
            # Normal mod: iki ardışık pozitif -> Kritik'e geç
            self._consecutive = self._consecutive + 1 if positive else 0
            if self._consecutive >= s.qod_consecutive_required:
                self.is_critical = True
                self._session_age_s = 0.0
                self._consecutive = 0
                decision.should_be_critical = True
                decision.fired_this_cycle = True
        else:
            # Kritik mod: bırakma koşulları
            self._session_age_s += dt_s
            high_conf = ctx.vehicle_conf >= s.qod_release_conf and ctx.plate_ocr_conf >= s.qod_release_conf
            timed_out = self._session_age_s >= s.qod_max_session_s
            out_of_roi = (not ctx.vehicle_present) or (ctx.vehicle_norm_y2 < s.qod_roi_line - 0.1)
            if high_conf or timed_out or out_of_roi:
                self.is_critical = False
                decision.should_be_critical = False
                decision.released_this_cycle = True
                if timed_out:
                    decision.reasons = ["release:timeout"]
                elif high_conf:
                    decision.reasons = ["release:yuksek_guven"]
                else:
                    decision.reasons = ["release:roi_disi"]

        decision.should_be_critical = self.is_critical
        return decision

    @property
    def session_age_s(self) -> float:
        return round(self._session_age_s, 2)
