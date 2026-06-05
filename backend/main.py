"""
FastAPI backend — REST + WebSocket + mock CAMARA 5G API'leri.

Mimari (3 parça): Mobil/Dashboard (ön yüz)  <->  bu Backend  <->  YZ hattı (ai/).
WebSocket /ws/ingest: ön yüz canlı kare yollar -> hat + QoD motoru çalışır ->
sonuç (FrameResult) hem ingest soketine yanıt olarak hem de /ws/detections
abonelerine yayınlanır. Riskli olaylar SQLite'a yazılır.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Set

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
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


@app.post("/api/test-video")
async def test_video(
    file: UploadFile = File(None),
    filename: str = Form(default=""),
    every_n: int = Form(default=3),
    scale: float = Form(default=0.5),
):
    """
    Video dosyasını YZ hattından geçirip annotated video + JSON özeti döner.

    Kullanım:
    - file: Video dosyası yükle (multipart)
    - filename: project-files/test-verisi/ içindeki dosya adı (örn: video_3.mp4)
    - every_n: Her N. kareyi işle
    - scale: Çözünürlük ölçeği (0.5 önerilir — işlem hızı için)
    """
    import tempfile
    import shutil
    from tools.test_video import process_video

    # Dosya yolu belirle
    if file and file.filename:
        # Yüklenen dosyayı geçici klasöre kaydet
        suffix = os.path.splitext(file.filename)[1] or ".mp4"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()
        video_path = tmp.name
        cleanup = True
    elif filename:
        # Proje içindeki mevcut dosyayı kullan
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        video_path = os.path.join(root, "project-files", "test-verisi", filename)
        cleanup = False
    else:
        raise HTTPException(status_code=400, detail="file veya filename gerekli")

    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"Video bulunamadı: {video_path}")

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(video_path))[0]
    out_video = os.path.join(out_dir, f"{base}_annotated.mp4")
    out_json = os.path.join(out_dir, f"{base}_results.json")

    try:
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(
            None,
            lambda: process_video(
                video_path=video_path,
                every_n=every_n,
                scale=scale,
                out_path=out_video,
                json_out=out_json,
            )
        )
    finally:
        if cleanup:
            os.unlink(video_path)

    return {
        **summary,
        "output_video_url": f"/output/{base}_annotated.mp4" if os.path.exists(out_video) else None,
        "output_json_url": f"/output/{base}_results.json" if os.path.exists(out_json) else None,
    }


@app.get("/api/test-video/files")
async def list_test_videos():
    """Proje içindeki test videoları listele."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_dir = os.path.join(root, "project-files", "test-verisi")
    if not os.path.isdir(test_dir):
        return {"files": []}
    files = [f for f in os.listdir(test_dir)
             if f.lower().endswith((".mp4", ".avi", ".mov", ".mkv"))]
    return {"files": sorted(files), "directory": test_dir}


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


# Annotated video çıktısını servis et
_output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
os.makedirs(_output_dir, exist_ok=True)
app.mount("/output", StaticFiles(directory=_output_dir), name="output")

# Web dashboard'u kök yoldan servis et (varsa)
_frontend = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
