"""
FastAPI backend — REST + WebSocket + mock CAMARA 5G API'leri.

Yenilikler (2026-06-06):
  - JWT RS256 kimlik doğrulama (ÖTR zorunlusu)
  - Rate limiting 100 req/dak (ÖTR zorunlusu)
  - /api/statistics, /api/events/{id}, /api/events/export, /api/vehicles/{plate}
  - Olay filtreleme (from_ts, to_ts, level, vtype)
  - /camara/qod/sessions GET (aktif oturum listesi)
  - Uçtan uca gecikme ölçümü (client_ts → total_latency_ms)
  - Prometheus /metrics endpoint
  - WS frame boyutu limiti (5 MB)
  - /api/health zenginleştirme (uptime, event_count, ws_connections)
"""
import asyncio
import io
import csv
import os
import time
from contextlib import asynccontextmanager
from typing import Optional, Set

import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from ai.pipeline import Pipeline
from ai.schema import EventRecord, FrameResult
from ai.detector import resolve_mode
from backend.auth import get_jwt_manager, require_auth
from backend.db import EventStore
from backend.metrics import (
    events_recorded_total,
    frame_inference_ms,
    frame_total_latency_ms,
    qod_sessions_total,
    ws_active_connections,
)
from backend.qod_manager import QoDManager
from backend.camara.number_verification import MockNumberVerification
from backend.frames import decode_data_url, decode_jpeg
from config.settings import get_settings

settings = get_settings()
limiter = Limiter(key_func=get_remote_address, default_limits=[f"{settings.rate_limit}/minute"])
_start_time = time.time()


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
            events_recorded_total.inc()


state: Optional[AppState] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = AppState()
    yield
    if state:
        state.store.close()


app = FastAPI(
    title="Akıllı Yol Güvenliği — 5G & YZ Backend",
    version="1.1.0",
    description="TEKNOFEST 2026 · CAMARA QoD + Number Verification + YZ Risk Motoru",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

Instrumentator().instrument(app).expose(app)


# ──────────────────────────────────────────────────────────────────────────────
# CAMARA
# ──────────────────────────────────────────────────────────────────────────────

class NumVerifyRequest(BaseModel):
    device_token: str
    phone_number: str


@app.post("/camara/number-verification:verify", tags=["camara"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def number_verification(request: Request, req: NumVerifyRequest):
    """CAMARA Number Verification — sessiz SIM doğrulama. Başarılıysa RS256 JWT döner."""
    verified = state.numverif.verify(req.device_token, req.phone_number)
    token = None
    if verified:
        token = get_jwt_manager().issue(req.phone_number, extra={"device": req.device_token})
    return {"devicePhoneNumberVerified": verified, "token": token}


class QoDSessionRequest(BaseModel):
    device: str = "device-guard-01"
    qos_profile: str = "QOS_S_HIGH_THROUGHPUT"
    duration_s: Optional[float] = None
    requested_mbps: Optional[int] = None


@app.post("/camara/qod/sessions", tags=["camara"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def qod_create(request: Request, req: QoDSessionRequest):
    """CAMARA QoD — manuel oturum açma (tetik motoru bunu otomatik de yapar)."""
    sess = state.qod.provider.create_session(
        device=req.device, qos_profile=req.qos_profile,
        duration_s=req.duration_s, requested_mbps=req.requested_mbps,
    )
    qod_sessions_total.inc()
    return {
        "sessionId": sess.id,
        "qosProfile": sess.qos_profile,
        "requestedMbps": sess.requested_mbps,
        "duration": sess.duration_s,
        "status": sess.status,
    }


@app.get("/camara/qod/sessions", tags=["camara"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def qod_list_sessions(request: Request):
    """CAMARA QoD — aktif oturum listesi."""
    sessions = []
    for sid, sess in state.qod.provider._sessions.items():
        sessions.append({
            "sessionId": sess.id,
            "device": sess.device,
            "qosProfile": sess.qos_profile,
            "requestedMbps": sess.requested_mbps,
            "durationS": sess.duration_s,
            "ageS": round(sess.age_s, 2),
            "status": sess.status,
            "expired": sess.expired(),
        })
    return {"sessions": sessions, "count": len(sessions)}


@app.delete("/camara/qod/sessions/{sid}", tags=["camara"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def qod_delete(request: Request, sid: str):
    """CAMARA QoD — oturumu kapat, bant 5 Mbps'e döner."""
    ok = state.qod.provider.delete_session(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": True, "sessionId": sid}


# ──────────────────────────────────────────────────────────────────────────────
# REST — Sistem
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/health", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def health(request: Request):
    """Sistem sağlık kontrolü — uptime, AI modu, WS bağlantı sayısı."""
    return {
        "status": "ok",
        "ai_mode": state.ai_mode,
        "detector": state.pipeline.mode_name,
        "qod_mode": state.qod.status().mode,
        "version": app.version,
        "uptime_s": round(time.time() - _start_time, 1),
        "event_count": state.store.count(),
        "ws_connections": len(state.subscribers),
    }


@app.get("/api/qod/status", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def qod_status(request: Request):
    """QoD bant durumu + bandwidth_efficiency."""
    st = state.qod.status()
    return {**st.model_dump(), "bandwidth_efficiency": state.qod.bandwidth_efficiency()}


# ──────────────────────────────────────────────────────────────────────────────
# REST — Olaylar
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/events", tags=["events"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def events(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    min_score: int = Query(default=0, ge=0, le=100),
    from_ts: Optional[float] = Query(default=None, description="Başlangıç timestamp (epoch saniye)"),
    to_ts: Optional[float] = Query(default=None, description="Bitiş timestamp (epoch saniye)"),
    level: Optional[str] = Query(default=None, description="Risk seviyesi: LOW|MEDIUM|HIGH|CRITICAL"),
    vtype: Optional[str] = Query(default=None, description="Araç tipi: car|truck|bus|motorcycle"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Riskli olay listesi — filtreleme ve sayfalama destekli."""
    return [e.model_dump() for e in state.store.list(
        limit=limit, min_score=min_score,
        from_ts=from_ts, to_ts=to_ts, level=level, vtype=vtype,
    )]


@app.get("/api/events/export", tags=["events"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def events_export(
    request: Request,
    min_score: int = Query(default=0, ge=0, le=100),
    from_ts: Optional[float] = Query(default=None),
    to_ts: Optional[float] = Query(default=None),
    level: Optional[str] = Query(default=None),
    vtype: Optional[str] = Query(default=None),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Tüm olayları CSV formatında indir — jüri değerlendirmesi için."""
    evs = state.store.list(
        limit=10000, min_score=min_score,
        from_ts=from_ts, to_ts=to_ts, level=level, vtype=vtype,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "ts", "plate", "vtype", "speed_kmh",
                     "risk_score", "risk_level", "factors", "mode"])
    for e in evs:
        writer.writerow([e.id, e.ts, e.plate, e.vtype, e.speed_kmh,
                         e.risk_score, e.risk_level, e.factors, e.mode])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events.csv"},
    )


@app.get("/api/events/{event_id}", tags=["events"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def event_detail(
    request: Request,
    event_id: int,
    _auth: Optional[dict] = Depends(require_auth),
):
    """Tek olay detayı — ID ile sorgulama."""
    ev = state.store.get(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail=f"Olay bulunamadı: id={event_id}")
    return ev.model_dump()


# ──────────────────────────────────────────────────────────────────────────────
# REST — İstatistik & Araçlar
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/statistics", tags=["analytics"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def statistics(
    request: Request,
    period_s: float = Query(default=3600.0, ge=60.0, le=86400.0,
                            description="İstatistik periyodu (saniye, varsayılan 1 saat)"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """
    Sistem istatistikleri — jüri için anlık performans kanıtı.

    Döndürür: olay sayısı, high-risk count, ortalama hız, risk dağılımı,
    QoD tetik sayısı, bant genişliği verimliliği.
    """
    db_stats = state.store.statistics(period_s=period_s)
    return {
        **db_stats,
        "qod_trigger_count": state.qod._critical_cycles,
        "bandwidth_efficiency": state.qod.bandwidth_efficiency(),
        "qod_mode": state.qod.status().mode,
        "bandwidth_mbps": state.qod.provider.current_bandwidth_mbps(),
    }


@app.get("/api/vehicles", tags=["vehicles"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def vehicles(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Plaka bazlı araç özeti — max hız, max risk, görülme sayısı."""
    return state.store.vehicles(limit=limit)


@app.get("/api/vehicles/{plate}", tags=["vehicles"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def vehicle_events(
    request: Request,
    plate: str,
    limit: int = Query(default=100, ge=1, le=500),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Belirli plakaya ait tüm olay geçmişi — tarih sıralı (yeniden eskiye)."""
    evs = state.store.vehicles_by_plate(plate.upper(), limit=limit)
    if not evs:
        raise HTTPException(status_code=404, detail=f"Plaka bulunamadı: {plate}")
    return [e.model_dump() for e in evs]


@app.post("/api/clear", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def clear(request: Request):
    """Olay veritabanını sıfırla — test ve demo için."""
    state.store.clear()
    return {"cleared": True}


# ──────────────────────────────────────────────────────────────────────────────
# REST — Test Video
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/api/test-video", tags=["tools"])
@limiter.limit("10/minute")
async def test_video(
    request: Request,
    file: UploadFile = File(None),
    filename: str = Form(default=""),
    every_n: int = Form(default=3),
    scale: float = Form(default=0.5),
):
    """Video dosyasını YZ hattından geçirip annotated video + JSON özeti döner."""
    import tempfile
    import shutil
    from tools.test_video import process_video

    if file and file.filename:
        suffix = os.path.splitext(file.filename)[1] or ".mp4"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        shutil.copyfileobj(file.file, tmp)
        tmp.flush()
        video_path = tmp.name
        cleanup = True
    elif filename:
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


@app.get("/api/test-video/files", tags=["tools"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def list_test_videos(request: Request):
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

async def _process_frame(frame: np.ndarray, client_ts: Optional[float]) -> dict:
    server_recv_ts = time.time()
    result, ctx = state.pipeline.process(frame, critical=state.qod.is_critical)
    qod_status = state.qod.step(ctx, dt_s=state.settings.qod_eval_period_ms / 1000.0)

    if qod_status.mode == "CRITICAL" and result.mode == "NORMAL":
        qod_sessions_total.inc()

    result.qod = qod_status
    result.mode = qod_status.mode
    state.maybe_record(result)

    # Gecikme ölçümü
    inference_done_ts = time.time()
    result.total_latency_ms = round((inference_done_ts - server_recv_ts) * 1000, 1)
    if client_ts is not None and client_ts > 0:
        result.total_latency_ms = round((inference_done_ts - client_ts) * 1000, 1)

    frame_inference_ms.observe(result.latency_ms)
    frame_total_latency_ms.observe(result.total_latency_ms)

    payload = result.model_dump()
    await state.broadcast(payload)
    return payload


@app.websocket("/ws/ingest")
async def ws_ingest(ws: WebSocket):
    """Ön yüz canlı kare yollar; her kare işlenip sonuç aynı sokete dönülür."""
    await ws.accept()
    ws_active_connections.labels(endpoint="ingest").inc()
    try:
        while True:
            msg = await ws.receive()

            # Frame boyutu limiti
            raw = msg.get("bytes") or (msg.get("text", "") or "").encode()
            if len(raw) > state.settings.ws_max_frame_bytes:
                await ws.send_json({"error": "frame too large"})
                continue

            frame = None
            client_ts: Optional[float] = None

            if msg.get("bytes") is not None:
                frame = decode_jpeg(msg["bytes"])
            elif msg.get("text") is not None:
                txt = msg["text"]
                if txt.startswith("{"):
                    import json as _json
                    obj = _json.loads(txt)
                    frame = decode_data_url(obj.get("frame", ""))
                    client_ts = obj.get("client_ts")
                else:
                    frame = decode_data_url(txt)

            if frame is None:
                await ws.send_json({"error": "frame decode failed"})
                continue

            payload = await _process_frame(frame, client_ts)
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        ws_active_connections.labels(endpoint="ingest").dec()


@app.websocket("/ws/detections")
async def ws_detections(ws: WebSocket):
    """Salt-okuma abone: işlenen her karenin sonucunu yayın olarak alır."""
    await ws.accept()
    state.subscribers.add(ws)
    ws_active_connections.labels(endpoint="detections").inc()
    try:
        while True:
            await ws.receive_text()  # ping/keepalive
    except WebSocketDisconnect:
        pass
    finally:
        state.subscribers.discard(ws)
        ws_active_connections.labels(endpoint="detections").dec()


# ──────────────────────────────────────────────────────────────────────────────
# Statik dosyalar
# ──────────────────────────────────────────────────────────────────────────────

_output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
os.makedirs(_output_dir, exist_ok=True)
app.mount("/output", StaticFiles(directory=_output_dir), name="output")

_frontend = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
