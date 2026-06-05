"""
Mock CAMARA Quality on Demand (QoD) API.

GSMA CAMARA QoD API'sinin (POST/DELETE /sessions) sözleşmesini taklit eder.
Final yarışmada Turkcell gerçek uç noktayı sağlayacak; geliştirme/2. aşama için
bu mock, aynı arayüzle bant genişliğini Normal↔Kritik arasında değiştirir.

Gerçek API'ye geçiş: yalnızca base_url + kimlik doğrulama değişir; çağrı sözleşmesi
(qosProfile, duration, device) aynı kalır.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from config.settings import get_settings

# CAMARA standardına yakın QoS profilleri
QOS_PROFILES = {
    "QOS_E_NORMAL": "best-effort",
    "QOS_L_LOW_LATENCY": "low-latency",
    "QOS_S_HIGH_THROUGHPUT": "high-throughput",   # kritik mod
}


@dataclass
class QoDSession:
    id: str
    device: str
    qos_profile: str
    requested_mbps: int
    duration_s: float
    created_at: float = field(default_factory=time.time)
    status: str = "ACTIVE"

    @property
    def age_s(self) -> float:
        return time.time() - self.created_at

    def expired(self) -> bool:
        return self.age_s >= self.duration_s


class MockQoDProvider:
    """Tek aktif QoD oturumu yönetir (senaryo: tek kamera/tek akış)."""

    def __init__(self, settings=None):
        self.s = settings or get_settings()
        self._sessions: Dict[str, QoDSession] = {}
        self._active_id: Optional[str] = None

    # ── CAMARA: POST /sessions ────────────────────────────────────────────────
    def create_session(self, device: str, qos_profile: str = "QOS_S_HIGH_THROUGHPUT",
                       duration_s: Optional[float] = None,
                       requested_mbps: Optional[int] = None) -> QoDSession:
        self._expire_due()
        sid = str(uuid.uuid4())
        sess = QoDSession(
            id=sid,
            device=device,
            qos_profile=qos_profile,
            requested_mbps=requested_mbps or self.s.camara_qod_critical_mbps,
            duration_s=duration_s if duration_s is not None else self.s.qod_max_session_s,
        )
        self._sessions[sid] = sess
        self._active_id = sid
        return sess

    # ── CAMARA: DELETE /sessions/{id} ─────────────────────────────────────────
    def delete_session(self, sid: str) -> bool:
        sess = self._sessions.pop(sid, None)
        if sess:
            sess.status = "DELETED"
        if self._active_id == sid:
            self._active_id = None
        return sess is not None

    def get_session(self, sid: str) -> Optional[QoDSession]:
        return self._sessions.get(sid)

    def _expire_due(self) -> None:
        if self._active_id:
            sess = self._sessions.get(self._active_id)
            if sess and sess.expired():
                sess.status = "EXPIRED"
                self._sessions.pop(self._active_id, None)
                self._active_id = None

    # ── Bant genişliği simülatörü ─────────────────────────────────────────────
    def current_bandwidth_mbps(self) -> int:
        self._expire_due()
        if self._active_id:
            return self._sessions[self._active_id].requested_mbps
        return self.s.camara_qod_normal_mbps

    def current_latency_ms(self) -> int:
        self._expire_due()
        base = self.s.camara_network_latency_ms
        # QoD aktifken düşük gecikme (URLLC benzeri öncelik)
        return int(base * 0.4) if self._active_id else base

    @property
    def active_session_id(self) -> Optional[str]:
        self._expire_due()
        return self._active_id

    def status(self) -> dict:
        return {
            "active_session_id": self.active_session_id,
            "bandwidth_mbps": self.current_bandwidth_mbps(),
            "latency_ms": self.current_latency_ms(),
            "mode": "CRITICAL" if self.active_session_id else "NORMAL",
        }
