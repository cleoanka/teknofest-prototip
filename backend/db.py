"""
Olay deposu — SQLite (basit, sıfır kurulum). Üretimde PostgreSQL'e taşınabilir.

Risk seviyesi MEDIUM ve üzeri tespitler kalıcı olay olarak kaydedilir; /api/events
ile sorgulanır. Senaryo: güvenlik görevlisi geçmiş ihlalleri inceler.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import List, Optional

from ai.schema import EventRecord


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

    def list(self, limit: int = 50, min_score: int = 0) -> List[EventRecord]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM events WHERE risk_score >= ?
                   ORDER BY ts DESC LIMIT ?""",
                (min_score, limit),
            ).fetchall()
        return [EventRecord(**dict(r)) for r in rows]

    def vehicles(self, limit: int = 50) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT plate, vtype, MAX(speed_kmh) as max_speed,
                          MAX(risk_score) as max_risk, COUNT(*) as sightings,
                          MAX(ts) as last_seen
                   FROM events WHERE plate IS NOT NULL
                   GROUP BY plate ORDER BY last_seen DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM events")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
