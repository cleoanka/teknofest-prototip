"""
FastAPI backend — REST + WebSocket + mock CAMARA 5G API'leri.

Mimari (3 parça): Mobil/Dashboard (ön yüz)  <->  bu Backend  <->  YZ hattı (ai/).
WebSocket /ws/ingest: ön yüz canlı kare yollar -> hat + QoD motoru çalışır ->
sonuç (FrameResult) hem ingest soketine yanıt olarak hem de /ws/detections
abonelerine yayınlanır. Riskli olaylar SQLite'a yazılır.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Set

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai.pipeline import Pipeline
from ai.schema import EventRecord, FrameResult
from ai.detector import resolve_mode
from backend.qod_manager import QoDManager
from backend.db import EventStore
from backend.camara.number_verification import MockNumberVerification
from backend.frames import decode_data_url, decode_jpeg
from config.settings import get_settings


class AppState:
    def __init__(self):
        self.settings = get_settings()
        self.pipeline = Pipeline(settings=self.settings)
        self.qod = QoDManager(settings=self.settings)
        self.store = EventStore(self.settings.db_path)
        self.numverif = MockNumberVerification()
        self.subscribers: Set[WebSocket] = set()
        self.ai_mode = resolve_mode(self.settings)
        self._last_event_ts = 0.0

    async def broadcast(self, payload: dict) -> None:
        dead = []
        for ws in list(self.subscribers):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subscribers.discard(ws)

    def maybe_record(self, result: FrameResult) -> None:
        # MEDIUM+ riskleri, saniyede en çok bir kez kaydet (spam önleme)
        if result.risk.score >= 30 and (result.ts - self._last_event_ts) > 1.0:
            self._last_event_ts = result.ts
            self.store.add(EventRecord(
                ts=result.ts,
                plate=result.vehicle.plate.text,
                vtype=result.vehicle.vtype,
                speed_kmh=result.vehicle.speed_kmh,
                risk_score=result.risk.score,
                risk_level=result.risk.level,
                factors=",".join(result.risk.factors),
                mode=result.mode,
            ))


state: AppState | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = AppState()
    yield
    if state:
        state.store.close()


app = FastAPI(title="Akıllı Yol Güvenliği — 5G & YZ Backend", version="1.0.0",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ──────────────────────────────────────────────────────────────────────────────
# REST
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "ai_mode": state.ai_mode,
        "detector": state.pipeline.mode_name,
        "qod_mode": state.qod.status().mode,
        "version": app.version,
    }


class NumVerifyRequest(BaseModel):
    device_token: str
    phone_number: str


@app.post("/camara/number-verification:verify")
async def number_verification(req: NumVerifyRequest):
    """CAMARA Number Verification — sessiz SIM doğrulama (SMS yok)."""
    verified = state.numverif.verify(req.device_token, req.phone_number)
    token = state.numverif.issue_token(req.phone_number) if verified else None
    return {"devicePhoneNumberVerified": verified, "token": token}


class QoDSessionRequest(BaseModel):
    device: str = "device-guard-01"
    qos_profile: str = "QOS_S_HIGH_THROUGHPUT"
    duration_s: float | None = None
    requested_mbps: int | None = None


@app.post("/camara/qod/sessions")
async def qod_create(req: QoDSessionRequest):
    """CAMARA QoD — manuel oturum açma (tetik motoru bunu otomatik de yapar)."""
    sess = state.qod.provider.create_session(
        device=req.device, qos_profile=req.qos_profile,
        duration_s=req.duration_s, requested_mbps=req.requested_mbps,
    )
    return {"sessionId": sess.id, "qosProfile": sess.qos_profile,
            "requestedMbps": sess.requested_mbps, "duration": sess.duration_s,
            "status": sess.status}


@app.delete("/camara/qod/sessions/{sid}")
async def qod_delete(sid: str):
    ok = state.qod.provider.delete_session(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": True, "sessionId": sid}


@app.get("/api/qod/status")
async def qod_status():
    st = state.qod.status()
    return {**st.model_dump(), "bandwidth_efficiency": state.qod.bandwidth_efficiency()}


@app.get("/api/events")
async def events(limit: int = 50, min_score: int = 0):
    return [e.model_dump() for e in state.store.list(limit=limit, min_score=min_score)]


@app.get("/api/vehicles")
async def vehicles(limit: int = 50):
    return state.store.vehicles(limit=limit)


@app.post("/api/clear")
async def clear():
    state.store.clear()
    return {"cleared": True}


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket
# ──────────────────────────────────────────────────────────────────────────────
async def _process_frame(frame: np.ndarray) -> dict:
    result, ctx = state.pipeline.process(frame, critical=state.qod.is_critical)
    qod_status = state.qod.step(ctx, dt_s=state.settings.qod_eval_period_ms / 1000.0)
    result.qod = qod_status
    result.mode = qod_status.mode
    # Kritik moda yeni geçildiyse, bir sonraki karede plaka/sürücü zaten okunacak
    state.maybe_record(result)
    payload = result.model_dump()
    await state.broadcast(payload)
    return payload


@app.websocket("/ws/ingest")
async def ws_ingest(ws: WebSocket):
    """Ön yüz canlı kare yollar; her kare işlenip sonuç aynı sokete dönülür."""
    await ws.accept()
    try:
        while True:
            msg = await ws.receive()
            frame = None
            if msg.get("bytes") is not None:
                frame = decode_jpeg(msg["bytes"])
            elif msg.get("text") is not None:
                txt = msg["text"]
                if txt.startswith("{"):
                    import json
                    obj = json.loads(txt)
                    frame = decode_data_url(obj.get("frame", ""))
                else:
                    frame = decode_data_url(txt)
            if frame is None:
                await ws.send_json({"error": "frame decode failed"})
                continue
            payload = await _process_frame(frame)
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"error": str(e)})
        except Exception:
            pass


@app.websocket("/ws/detections")
async def ws_detections(ws: WebSocket):
    """Salt-okuma abone: işlenen her karenin sonucunu yayın olarak alır."""
    await ws.accept()
    state.subscribers.add(ws)
    try:
        while True:
            await ws.receive_text()  # ping/keepalive
    except WebSocketDisconnect:
        pass
    finally:
        state.subscribers.discard(ws)


# Web dashboard'u kök yoldan servis et (varsa)
import os  # noqa: E402
_frontend = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
