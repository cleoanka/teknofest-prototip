"""
Olay deposu — SQLite (basit, sıfır kurulum). Üretimde PostgreSQL'e taşınabilir.

Risk seviyesi MEDIUM ve üzeri tespitler kalıcı olay olarak kaydedilir; /api/events
ile sorgulanır. Senaryo: güvenlik görevlisi geçmiş ihlalleri inceler.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import List, Optional

from ai.schema import EventRecord

_VALID_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


class EventStore:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    plate TEXT,
                    vtype TEXT,
                    speed_kmh REAL,
                    risk_score INTEGER DEFAULT 0,
                    risk_level TEXT DEFAULT 'LOW',
                    factors TEXT DEFAULT '',
                    mode TEXT DEFAULT 'NORMAL',
                    snapshot TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_plate ON events(plate)"
            )
            self._conn.commit()

    def add(self, ev: EventRecord) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO events (ts, plate, vtype, speed_kmh, risk_score,
                   risk_level, factors, mode, snapshot)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (ev.ts, ev.plate, ev.vtype, ev.speed_kmh, ev.risk_score,
                 ev.risk_level, ev.factors, ev.mode, ev.snapshot),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get(self, event_id: int) -> Optional[EventRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM events WHERE id = ?", (event_id,)
            ).fetchone()
        return EventRecord(**dict(row)) if row else None

    def list(
        self,
        limit: int = 50,
        min_score: int = 0,
        from_ts: Optional[float] = None,
        to_ts: Optional[float] = None,
        level: Optional[str] = None,
        vtype: Optional[str] = None,
    ) -> List[EventRecord]:
        q = "SELECT * FROM events WHERE risk_score >= ?"
        params: list = [min_score]
        if from_ts is not None:
            q += " AND ts >= ?"
            params.append(from_ts)
        if to_ts is not None:
            q += " AND ts <= ?"
            params.append(to_ts)
        if level is not None and level in _VALID_LEVELS:
            q += " AND risk_level = ?"
            params.append(level)
        if vtype is not None:
            q += " AND vtype = ?"
            params.append(vtype)
        q += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [EventRecord(**dict(r)) for r in rows]

    def vehicles(self, limit: int = 50) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT plate, vtype, MAX(speed_kmh) as max_speed,
                          MAX(risk_score) as max_risk, COUNT(*) as sightings,
                          MAX(ts) as last_seen
                   FROM events WHERE plate IS NOT NULL AND plate != ''
                   GROUP BY plate ORDER BY last_seen DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def vehicles_by_plate(self, plate: str, limit: int = 100) -> List[EventRecord]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM events WHERE plate = ?
                   ORDER BY ts DESC LIMIT ?""",
                (plate, limit),
            ).fetchall()
        return [EventRecord(**dict(r)) for r in rows]

    def statistics(self, period_s: float = 3600.0) -> dict:
        """Son `period_s` saniyedeki istatistikler."""
        since = time.time() - period_s
        with self._lock:
            total_row = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts >= ?", (since,)
            ).fetchone()
            high_risk_row = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE ts >= ? AND risk_score >= 60",
                (since,),
            ).fetchone()
            avg_speed_row = self._conn.execute(
                "SELECT AVG(speed_kmh) FROM events WHERE ts >= ? AND speed_kmh IS NOT NULL",
                (since,),
            ).fetchone()
            breakdown_rows = self._conn.execute(
                """SELECT risk_level, COUNT(*) as cnt
                   FROM events WHERE ts >= ?
                   GROUP BY risk_level""",
                (since,),
            ).fetchall()
        breakdown = {lvl: 0 for lvl in _VALID_LEVELS}
        for row in breakdown_rows:
            breakdown[row["risk_level"]] = row["cnt"]
        avg_spd = avg_speed_row[0]
        return {
            "period_s": period_s,
            "event_count": total_row[0],
            "high_risk_count": high_risk_row[0],
            "avg_speed_kmh": round(avg_spd, 1) if avg_spd is not None else None,
            "risk_breakdown": breakdown,
        }

    def hourly_summary(self, hours: int = 24) -> list:
        """Son N saatin saatlik olay dağılımı — grafik için."""
        since = time.time() - hours * 3600
        with self._lock:
            rows = self._conn.execute(
                """SELECT CAST((ts - ?) / 3600 AS INTEGER) as hour_offset,
                          COUNT(*) as count,
                          AVG(risk_score) as avg_score,
                          MAX(risk_score) as max_score
                   FROM events WHERE ts >= ?
                   GROUP BY hour_offset
                   ORDER BY hour_offset""",
                (since, since),
            ).fetchall()
        return [
            {
                "hour_offset": r["hour_offset"],
                "count": r["count"],
                "avg_score": round(r["avg_score"], 1) if r["avg_score"] else 0,
                "max_score": r["max_score"] or 0,
            }
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return row[0]

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM events")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
