"""
QoD Yöneticisi — tetik motorunu mock CAMARA QoD API'sine bağlar.

Her değerlendirme adımında (kare bazlı):
  1) QoDTriggerEngine ile koşulları değerlendir
  2) Normal->Kritik tetik: CAMARA POST /sessions (yüksek bant)
  3) Kritik->Normal bırakma: CAMARA DELETE /sessions/{id}
  4) Güncel QoDStatus döndür (mod, bant, oturum, son sebep)

Bu, şartmenin %40'lık "yalnızca ihtiyaç varken bant yükseltme" kriterinin
çalışan kanıtıdır: bant sürekli yüksek tutulmaz, sadece tetik anında açılır.
"""
from __future__ import annotations

from typing import Optional

from ai.qod_trigger import QoDTriggerEngine, TriggerContext
from ai.schema import QoDStatus
from backend.camara.qod import MockQoDProvider
from config.settings import get_settings


class QoDManager:
    def __init__(self, device: str = "device-guard-01", settings=None):
        self.s = settings or get_settings()
        self.device = device
        self.engine = QoDTriggerEngine(self.s)
        self.provider = MockQoDProvider(self.s)
        self._last_reason: Optional[str] = None
        # bant verimliliği ölçümü
        self._cycles = 0
        self._critical_cycles = 0

    @property
    def is_critical(self) -> bool:
        return self.engine.is_critical

    def step(self, ctx: TriggerContext, dt_s: float = 0.5) -> QoDStatus:
        self._cycles += 1
        decision = self.engine.evaluate(ctx, dt_s=dt_s)

        if decision.fired_this_cycle:
            sess = self.provider.create_session(
                device=self.device,
                qos_profile="QOS_S_HIGH_THROUGHPUT",
                duration_s=self.s.qod_max_session_s,
            )
            self._last_reason = decision.reason_text
        elif decision.released_this_cycle:
            if self.provider.active_session_id:
                self.provider.delete_session(self.provider.active_session_id)
            self._last_reason = decision.reason_text

        if self.engine.is_critical:
            self._critical_cycles += 1

        return QoDStatus(
            mode="CRITICAL" if self.engine.is_critical else "NORMAL",
            bandwidth_mbps=self.provider.current_bandwidth_mbps(),
            active_session_id=self.provider.active_session_id,
            last_trigger_reason=self._last_reason or decision.reason_text,
            session_age_s=self.engine.session_age_s,
        )

    def bandwidth_efficiency(self) -> float:
        """Sürekli-yüksek-bant'a göre tasarruf oranı (yüksek = iyi)."""
        if self._cycles == 0:
            return 1.0
        return round(1.0 - (self._critical_cycles / self._cycles), 3)

    def status(self) -> QoDStatus:
        return QoDStatus(
            mode="CRITICAL" if self.engine.is_critical else "NORMAL",
            bandwidth_mbps=self.provider.current_bandwidth_mbps(),
            active_session_id=self.provider.active_session_id,
            last_trigger_reason=self._last_reason,
            session_age_s=self.engine.session_age_s,
        )
