"""
FastAPI backend — REST + WebSocket + mock CAMARA 5G API'leri.

v1.1: JWT RS256, rate limiting, statistics, filtering, Prometheus
v1.2: JWT key persistence, /api/settings, WS /ws/status, X-Total-Count, plate validation
v1.3: GZip, güvenlik başlıkları, X-Request-ID, qod/proof, offset pagination
v1.4: WS token auth, /api/health/deep, JSON loglama, X-Response-Time, OpenAPI tags
v1.5: CORS expose_headers, /api/system/info, qod/sessions/{sid}, export plate filter
"""
import asyncio
import io
import csv
import json
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from typing import Optional, Set

import uuid
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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

# ── Yapılandırılmış JSON Loglama ──────────────────────────────────────────────

class _JsonFormatter(logging.Formatter):
    """Her log satırını tek JSON satırına dönüştürür — üretim ortamı için."""
    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _configure_json_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # uvicorn access loglarını da JSON'a yönlendir
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lgr = logging.getLogger(name)
        lgr.handlers = []
        lgr.propagate = True


logger = logging.getLogger("roadguard")


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
    _configure_json_logging()
    state = AppState()
    logger.info("RoadGuard backend başlatıldı", extra={})
    yield
    if state:
        state.store.close()
    logger.info("RoadGuard backend kapatıldı", extra={})


_PLATE_RE = re.compile(r"^[0-9]{2}[A-Z][A-Z0-9]{0,2}[0-9]{2,5}$")


def _validate_plate(plate: str) -> str:
    """TR plaka formatını doğrula: NN+L[LL]+NNNN (örn. 34ABC1234). 422 fırlatır geçersizse."""
    p = plate.strip().upper()
    if not _PLATE_RE.match(p):
        raise HTTPException(status_code=422, detail=f"Geçersiz plaka formatı: {plate!r}")
    return p


_OPENAPI_TAGS = [
    {"name": "system", "description": "Sağlık kontrolü, ayarlar, sistem durumu"},
    {"name": "events", "description": "Riskli olay kaydı, sorgulama ve dışa aktarma"},
    {"name": "vehicles", "description": "Plaka bazlı araç geçmişi"},
    {"name": "analytics", "description": "İstatistik, saatlik özet, QoD kanıtı"},
    {"name": "camara", "description": "CAMARA QoD + Number Verification — 5G API"},
    {"name": "auth", "description": "JWT RS256 public key (JWKS)"},
    {"name": "tools", "description": "Test video işleme"},
]

app = FastAPI(
    title="Akıllı Yol Güvenliği — 5G & YZ Backend",
    version="1.5.0",
    description=(
        "**TEKNOFEST 2026** · CAMARA QoD + Number Verification + YZ Risk Motoru\n\n"
        "- JWT RS256 kimlik doğrulama (`/.well-known/jwks.json`)\n"
        "- Rate limiting: 100 istek/dk (slowapi)\n"
        "- CAMARA QoD dinamik bant yönetimi\n"
        "- WebSocket: `/ws/ingest`, `/ws/detections`, `/ws/status`\n"
        "- Prometheus metrikleri: `/metrics`\n\n"
        "> `REQUIRE_AUTH=true` ile tüm `/api/*` endpoint'leri Bearer token ister."
    ),
    openapi_tags=_OPENAPI_TAGS,
    lifespan=lifespan,
    swagger_ui_parameters={
        "docExpansion": "list",
        "defaultModelsExpandDepth": -1,
        "tryItOutEnabled": True,
        "filter": True,
        "persistAuthorization": True,
    },
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Özel response header'ların tarayıcı JS tarafından okunabilmesi için
    expose_headers=[
        "X-Total-Count", "X-Filtered-Count", "X-Offset",
        "X-Request-ID", "X-Response-Time",
        "Content-Disposition",
    ],
)


@app.middleware("http")
async def security_and_request_id(request: Request, call_next):
    """Güvenlik headerleri + X-Request-ID + X-Response-Time ekler."""
    t0 = time.perf_counter()
    req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    response.headers["X-Request-ID"] = req_id
    response.headers["X-Response-Time"] = f"{elapsed_ms}ms"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


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


@app.get("/camara/qod/sessions/{sid}", tags=["camara"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def qod_get_session(request: Request, sid: str):
    """CAMARA QoD — tek oturum detayı."""
    sess = state.qod.provider._sessions.get(sid)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"QoD oturumu bulunamadı: {sid}")
    return {
        "sessionId": sess.id,
        "device": sess.device,
        "qosProfile": sess.qos_profile,
        "requestedMbps": sess.requested_mbps,
        "durationS": sess.duration_s,
        "ageS": round(sess.age_s, 2),
        "status": sess.status,
        "expired": sess.expired(),
    }


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

@app.get("/api/ping", tags=["system"])
async def ping():
    """Ultralight gecikme ölçümü — sadece sunucu zaman damgası döner."""
    return {"pong": round(time.time(), 3)}


@app.get("/api/version", tags=["system"])
async def version_info():
    """API sürüm bilgisi — bağımlılıklar, Python sürümü, ortam."""
    import sys
    import platform
    return {
        "version": app.version,
        "title": app.title,
        "python": sys.version.split()[0],
        "platform": platform.system(),
        "ai_mode": state.ai_mode if state else "unknown",
        "camara_mode": get_settings().camara_mode,
        "uptime_s": round(time.time() - _start_time, 1),
        "build": "TEKNOFEST 2026",
    }


@app.get("/api/system/info", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def system_info(request: Request):
    """
    Sistem kaynak kullanımı — izleme ve performans takibi için.

    RAM, CPU, disk kullanımı (psutil varsa), süreç bilgisi, açık dosya sayısı.
    Yarışma jürisi bu endpoint ile sistemin kaynak verimliliğini doğrulayabilir.
    """
    info: dict = {
        "uptime_s": round(time.time() - _start_time, 1),
        "version": app.version,
        "event_count": state.store.count(),
        "ws_connections": len(state.subscribers),
    }
    try:
        import psutil
        proc = psutil.Process()
        with proc.oneshot():
            mem = proc.memory_info()
            cpu_pct = proc.cpu_percent(interval=None)
            open_files = len(proc.open_files())
            threads = proc.num_threads()
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        info["process"] = {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
            "cpu_pct": cpu_pct,
            "threads": threads,
            "open_files": open_files,
        }
        info["system"] = {
            "total_ram_mb": round(vm.total / 1024 / 1024, 1),
            "available_ram_mb": round(vm.available / 1024 / 1024, 1),
            "ram_used_pct": vm.percent,
            "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "disk_used_pct": round(disk.percent, 1),
        }
    except ImportError:
        info["psutil"] = "not installed — pip install psutil for resource metrics"
    except Exception as exc:
        info["psutil_error"] = str(exc)
    return info


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


@app.get("/api/health/deep", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def health_deep(request: Request):
    """
    Derin sağlık kontrolü — DB, QoD ve bellek durumu.

    `/api/health` anlık uptime dönerken bu endpoint her alt sistemi test eder.
    CI/CD probe ve izleme sistemleri için uygundur.
    """
    checks: dict = {}

    # DB bağlantısı
    try:
        count = state.store.count()
        checks["db"] = {"status": "ok", "event_count": count, "path": state.store.path}
    except Exception as exc:
        checks["db"] = {"status": "error", "detail": str(exc)}

    # QoD motoru
    try:
        qod_st = state.qod.status()
        checks["qod"] = {
            "status": "ok",
            "mode": qod_st.mode,
            "bandwidth_mbps": qod_st.bandwidth_mbps,
            "cycles": state.qod._cycles,
        }
    except Exception as exc:
        checks["qod"] = {"status": "error", "detail": str(exc)}

    # Bellek (psutil varsa)
    try:
        import psutil
        proc = psutil.Process()
        mem = proc.memory_info()
        checks["memory"] = {
            "status": "ok",
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
        }
    except ImportError:
        checks["memory"] = {"status": "unavailable", "detail": "psutil not installed"}
    except Exception as exc:
        checks["memory"] = {"status": "error", "detail": str(exc)}

    all_ok = all(c["status"] in ("ok", "unavailable") for c in checks.values())
    status_code = 200 if all_ok else 503
    body = {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "uptime_s": round(time.time() - _start_time, 1),
        "version": app.version,
        "ws_connections": len(state.subscribers),
    }
    return JSONResponse(content=body, status_code=status_code)


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
    offset: int = Query(default=0, ge=0, description="Sayfalama: atlanacak olay sayısı"),
    min_score: int = Query(default=0, ge=0, le=100),
    from_ts: Optional[float] = Query(default=None, description="Başlangıç timestamp (epoch saniye)"),
    to_ts: Optional[float] = Query(default=None, description="Bitiş timestamp (epoch saniye)"),
    level: Optional[str] = Query(default=None, description="Risk seviyesi: LOW|MEDIUM|HIGH|CRITICAL"),
    vtype: Optional[str] = Query(default=None, description="Araç tipi: car|truck|bus|motorcycle"),
    plate: Optional[str] = Query(default=None, description="Plaka içerik araması (kısmi eşleşme, ör: '34A')"),
    sort_by: str = Query(default="ts", description="Sıralama alanı: ts|risk_score|speed_kmh|id"),
    sort_dir: str = Query(default="desc", description="Sıralama yönü: asc|desc"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Riskli olay listesi — filtreleme, sıralama ve sayfalama destekli."""
    evs = state.store.list(
        limit=limit, offset=offset, min_score=min_score,
        from_ts=from_ts, to_ts=to_ts, level=level, vtype=vtype,
        plate=plate, sort_by=sort_by, sort_dir=sort_dir,
    )
    filtered_total = state.store.count_filtered(
        min_score=min_score, from_ts=from_ts, to_ts=to_ts, level=level, vtype=vtype, plate=plate,
    )
    response = JSONResponse(content=[e.model_dump() for e in evs])
    response.headers["X-Total-Count"] = str(state.store.count())
    response.headers["X-Filtered-Count"] = str(filtered_total)
    response.headers["X-Offset"] = str(offset)
    return response


@app.get("/api/events/summary", tags=["analytics"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def events_summary_route(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168, description="Son kaç saatin özeti (1–168)"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """
    Saatlik olay dağılımı — dashboard grafikleri için.

    Her saat için: olay sayısı, ortalama risk skoru, en yüksek risk skoru.
    """
    return {
        "hours": hours,
        "summary": state.store.hourly_summary(hours=hours),
    }


@app.get("/api/events/export", tags=["events"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def events_export(
    request: Request,
    min_score: int = Query(default=0, ge=0, le=100),
    from_ts: Optional[float] = Query(default=None),
    to_ts: Optional[float] = Query(default=None),
    level: Optional[str] = Query(default=None),
    vtype: Optional[str] = Query(default=None),
    plate: Optional[str] = Query(default=None, description="Plaka kısmi eşleşme filtresi"),
    sort_by: str = Query(default="ts", description="Sıralama alanı"),
    sort_dir: str = Query(default="desc", description="asc|desc"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Tüm olayları CSV formatında indir — jüri değerlendirmesi için."""
    evs = state.store.list(
        limit=10000, min_score=min_score,
        from_ts=from_ts, to_ts=to_ts, level=level, vtype=vtype,
        plate=plate, sort_by=sort_by, sort_dir=sort_dir,
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


@app.delete("/api/events", tags=["events"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def events_bulk_delete(
    request: Request,
    confirm: bool = Query(default=False, description="Silme işlemini onaylamak için true gönderin"),
    level: Optional[str] = Query(default=None, description="Sadece bu risk seviyesini sil"),
    min_score: int = Query(default=0, ge=0, le=100),
    from_ts: Optional[float] = Query(default=None),
    to_ts: Optional[float] = Query(default=None),
    vtype: Optional[str] = Query(default=None),
    plate: Optional[str] = Query(default=None),
    _auth: Optional[dict] = Depends(require_auth),
):
    """
    Toplu olay silme — filtre koşullarına uyan olayları siler.

    ?confirm=true zorunludur. Filtre belirtilmezse TÜM olaylar silinir.
    Demo sonrası veritabanını temizlemek için kullanın.
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Silme işlemi için ?confirm=true parametresi zorunludur",
        )
    deleted = state.store.delete_filtered(
        min_score=min_score, from_ts=from_ts, to_ts=to_ts,
        level=level, vtype=vtype, plate=plate,
    )
    return {"deleted": deleted, "remaining": state.store.count()}


@app.get("/api/events/heatmap", tags=["analytics"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def events_heatmap(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168, description="Kaç saatlik pencere (1–168)"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """
    Zaman × risk seviyesi ısı haritası verisi — dashboard renk gridleri için.

    Döndürür: NxM matris (satır=saat, sütun=risk_level).
    Her hücre o saatte o risk seviyesindeki olay sayısıdır.
    """
    since = time.time() - hours * 3600
    evs = state.store.list(limit=100000, from_ts=since)
    levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    # hour_offset → level → count
    grid: dict[int, dict[str, int]] = {}
    for e in evs:
        h = int((e.ts - since) / 3600)
        if h not in grid:
            grid[h] = {lvl: 0 for lvl in levels}
        if e.risk_level in grid[h]:
            grid[h][e.risk_level] += 1
    rows = [
        {"hour_offset": h, **grid[h]}
        for h in sorted(grid)
    ]
    return {
        "hours": hours,
        "levels": levels,
        "rows": rows,
        "total_events": len(evs),
    }


class TestEventBody(BaseModel):
    count: int = 5
    risk_level: str = "HIGH"
    plate_prefix: str = "34TEST"
    speed_kmh: float = 120.0
    spread_s: float = 3600.0


@app.post("/api/events/test", tags=["tools"])
@limiter.limit("20/minute")
async def inject_test_events(request: Request, body: TestEventBody):
    """
    Demo test olayları enjekte et — sunum öncesi veritabanını doldurmak için.

    count kadar olay oluşturur; risk_level, plaka öneki ve yayılım süresi ayarlanabilir.
    """
    import random
    LEVEL_SCORE = {"LOW": 20, "MEDIUM": 45, "HIGH": 70, "CRITICAL": 90}
    now = time.time()
    score = LEVEL_SCORE.get(body.risk_level.upper(), 50)
    added_ids = []
    for i in range(min(body.count, 100)):
        plate_suffix = f"{random.randint(1000, 9999)}"
        plate = f"{body.plate_prefix[:8]}{plate_suffix}"[:12]
        ev = EventRecord(
            ts=now - random.uniform(0, body.spread_s),
            plate=plate,
            risk_score=score + random.randint(-5, 5),
            risk_level=body.risk_level.upper(),
            factors="speed,test",
            mode="NORMAL",
            speed_kmh=body.speed_kmh + random.uniform(-10, 10),
        )
        eid = state.store.add(ev)
        added_ids.append(eid)
    return {
        "injected": len(added_ids),
        "ids": added_ids,
        "risk_level": body.risk_level.upper(),
        "total_events": state.store.count(),
    }


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


@app.delete("/api/events/{event_id}", tags=["events"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def delete_event(
    request: Request,
    event_id: int,
    _auth: Optional[dict] = Depends(require_auth),
):
    """Tek olay sil — ID ile. Bulunamazsa 404."""
    deleted = state.store.delete_by_id(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Olay bulunamadı: id={event_id}")
    return {"deleted": True, "id": event_id, "remaining": state.store.count()}


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


@app.get("/api/qod/proof", tags=["analytics"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def qod_proof(
    request: Request,
    _auth: Optional[dict] = Depends(require_auth),
):
    """
    ÖTR %40 bant verimliliği kriteri kanıtı — jüri değerlendirmesi için.

    CAMARA QoD ile Normal/Kritik mod arasında geçişleri izler.
    Normal modda 5 Mbps, Kritik modda yüksek bant kullanılır.
    Verimlilik = kritik_döngü / toplam_döngü × 100.
    """
    qod = state.qod
    total = qod._cycles
    critical = qod._critical_cycles
    efficiency = qod.bandwidth_efficiency()
    s = state.settings
    return {
        "criterion": "ÖTR Madde 4.2 — Dinamik Bant Yönetimi (CAMARA QoD)",
        "target_efficiency_pct": 40.0,
        "measured_efficiency_pct": round(efficiency * 100, 2),
        "meets_criterion": efficiency >= 0.40,
        "total_qod_cycles": total,
        "critical_mode_cycles": critical,
        "normal_mode_cycles": total - critical,
        "normal_bandwidth_mbps": s.camara_qod_normal_mbps,
        "critical_bandwidth_mbps": s.camara_qod_critical_mbps,
        "current_mode": qod.status().mode,
        "active_session_id": qod.status().active_session_id,
        "camara_mode": s.camara_mode,
        "qod_triggers": [
            "bbox_growth > threshold",
            "low_conf_consecutive > required",
            "ocr_conf < threshold",
            "roi_line_approach",
            "ambiguous_score in range",
        ],
    }


@app.get("/api/vehicles", tags=["vehicles"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def vehicles(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, description="Sayfalama: atlanacak araç sayısı"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Plaka bazlı araç özeti — max hız, max risk, görülme sayısı, sayfalama destekli."""
    rows = state.store.vehicles(limit=limit, offset=offset)
    response = JSONResponse(content=rows)
    response.headers["X-Total-Count"] = str(state.store.vehicles_count())
    response.headers["X-Offset"] = str(offset)
    return response


@app.get("/api/vehicles/{plate}/timeline", tags=["vehicles"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def vehicle_timeline(
    request: Request,
    plate: str,
    hours: int = Query(default=24, ge=1, le=168, description="Son kaç saatin zaman serisi"),
    _auth: Optional[dict] = Depends(require_auth),
):
    """
    Plakanın saatlik risk zaman serisi — güvenlik analistleri için.

    Her saat için: olay sayısı, ortalama hız, maksimum risk skoru.
    """
    validated = _validate_plate(plate)
    since = time.time() - hours * 3600
    evs = state.store.vehicles_by_plate(validated, limit=10000)
    evs_in_range = [e for e in evs if e.ts >= since]

    # Saatlik gruplama
    buckets: dict[int, list] = {}
    for e in evs_in_range:
        h = int((e.ts - since) / 3600)
        buckets.setdefault(h, []).append(e)

    timeline = []
    for h in sorted(buckets):
        group = buckets[h]
        speeds = [e.speed_kmh for e in group if e.speed_kmh is not None]
        timeline.append({
            "hour_offset": h,
            "count": len(group),
            "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "max_risk_score": max(e.risk_score for e in group),
            "risk_levels": list({e.risk_level for e in group}),
        })

    return {
        "plate": validated,
        "hours": hours,
        "event_count": len(evs_in_range),
        "timeline": timeline,
    }


@app.get("/api/vehicles/{plate}", tags=["vehicles"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def vehicle_events(
    request: Request,
    plate: str,
    limit: int = Query(default=100, ge=1, le=500),
    _auth: Optional[dict] = Depends(require_auth),
):
    """Belirli plakaya ait tüm olay geçmişi — tarih sıralı (yeniden eskiye)."""
    validated = _validate_plate(plate)
    evs = state.store.vehicles_by_plate(validated, limit=limit)
    if not evs:
        raise HTTPException(status_code=404, detail=f"Plaka bulunamadı: {validated}")
    return [e.model_dump() for e in evs]


@app.post("/api/clear", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def clear(request: Request):
    """Olay veritabanını sıfırla — test ve demo için."""
    state.store.clear()
    return {"cleared": True}


@app.get("/api/settings", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def get_current_settings(request: Request):
    """
    Mevcut ayarları göster (salt okunur, hassas bilgiler hariç).

    QoD eşikleri, rate limit, JWT TTL, CAMARA modu gibi demo sırasında
    izlenebilecek tüm parametreler burada görünür.
    """
    s = state.settings
    return {
        "ai_mode": s.ai_mode,
        "camara_mode": s.camara_mode,
        "require_auth": s.require_auth,
        "jwt_ttl_s": s.jwt_ttl_s,
        "rate_limit_per_min": s.rate_limit,
        "ws_max_frame_bytes": s.ws_max_frame_bytes,
        "qod": {
            "eval_period_ms": s.qod_eval_period_ms,
            "bbox_growth_threshold": s.qod_bbox_growth_threshold,
            "low_conf_threshold": s.qod_low_conf_threshold,
            "ocr_conf_threshold": s.qod_ocr_conf_threshold,
            "roi_line": s.qod_roi_line,
            "ambiguous_low": s.qod_ambiguous_low,
            "ambiguous_high": s.qod_ambiguous_high,
            "release_conf": s.qod_release_conf,
            "max_session_s": s.qod_max_session_s,
            "consecutive_required": s.qod_consecutive_required,
        },
        "camara_bandwidth": {
            "normal_mbps": s.camara_qod_normal_mbps,
            "critical_mbps": s.camara_qod_critical_mbps,
            "network_latency_ms": s.camara_network_latency_ms,
        },
        "speed": {
            "limit_kmh": s.speed_limit_kmh,
            "calibration_k": s.speed_calibration_k,
        },
    }


class SettingsPatch(BaseModel):
    """PATCH /api/settings — runtime ayar güncellemesi. Sadece QoD eşikleri ve hız limiti."""
    qod_bbox_growth_threshold: Optional[float] = None
    qod_low_conf_threshold: Optional[float] = None
    qod_ocr_conf_threshold: Optional[float] = None
    qod_roi_line: Optional[float] = None
    qod_ambiguous_low: Optional[float] = None
    qod_ambiguous_high: Optional[float] = None
    qod_release_conf: Optional[float] = None
    qod_max_session_s: Optional[float] = None
    qod_consecutive_required: Optional[int] = None
    speed_limit_kmh: Optional[float] = None


@app.patch("/api/settings", tags=["system"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def patch_settings(request: Request, body: SettingsPatch):
    """
    QoD eşiklerini ve hız limitini çalışma zamanında güncelle — demo sırasında
    jüri önünde sistemin hassasiyetini anlık değiştirmek için.

    Sadece QoD parametreleri ve hız limiti runtime'da değiştirilebilir.
    JWT / rate limit / DB değişiklikleri için sunucu yeniden başlatması gerekir.
    """
    s = state.settings
    changed = {}
    for field, value in body.model_dump(exclude_none=True).items():
        if hasattr(s, field):
            setattr(s, field, value)
            changed[field] = value
    if changed:
        # QoDTriggerEngine de aynı settings referansını kullanıyor, anında etki
        state.qod.engine.s = s
    return {"updated": changed, "message": f"{len(changed)} ayar güncellendi"}


@app.get("/.well-known/jwks.json", tags=["auth"])
async def jwks():
    """
    JWT public key — istemciler token doğrulaması için kullanır.
    RS256 algoritması; JWKS formatında PEM sunulur.
    """
    return {
        "issuer": "5g-roadguard",
        "algorithm": "RS256",
        "public_key_pem": get_jwt_manager().public_key_pem(),
    }


@app.post("/api/demo-token", tags=["auth"])
@limiter.limit("10/minute")
async def demo_token(request: Request, sub: str = "demo-user"):
    """
    Demo JWT üret — jüri sunumu ve geliştirme ortamı için.

    REQUIRE_AUTH=true modunda devre dışıdır. Swagger'dan `Authorize` düğmesine
    kopyalanarak tüm auth korumalı endpoint'ler test edilebilir.
    """
    s = get_settings()
    if s.require_auth:
        raise HTTPException(
            status_code=403,
            detail="Demo token sadece require_auth=False modda çalışır",
        )
    token = get_jwt_manager().issue(sub, extra={"role": "demo"})
    return {
        "token": token,
        "sub": sub,
        "ttl_s": s.jwt_ttl_s,
        "usage": f"Authorization: Bearer {token[:20]}...",
    }


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
    # Aşama 0 — hız Δt'si için istemci yakalama zamanını (video-zaman çizgisi) geçir;
    # yoksa pipeline wall-clock'a düşer.
    result, ctx = state.pipeline.process(
        frame, critical=state.qod.is_critical, frame_ts=client_ts)
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


def _ws_auth_ok(token: Optional[str]) -> bool:
    """WS bağlantısı için token doğrulama. require_auth=False ise her zaman True."""
    s = get_settings()
    if not s.require_auth:
        return True
    if not token:
        return False
    return get_jwt_manager().verify(token) is not None


@app.websocket("/ws/ingest")
async def ws_ingest(ws: WebSocket, token: Optional[str] = None):
    """Ön yüz canlı kare yollar; her kare işlenip sonuç aynı sokete dönülür.

    Auth aktifse `?token=<JWT>` query param ile bağlanın.
    """
    if not _ws_auth_ok(token):
        await ws.close(code=4001)
        return
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
                    obj = json.loads(txt)
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
async def ws_detections(ws: WebSocket, token: Optional[str] = None):
    """Salt-okuma abone: işlenen her karenin sonucunu yayın olarak alır.

    Auth aktifse `?token=<JWT>` query param ile bağlanın.
    """
    if not _ws_auth_ok(token):
        await ws.close(code=4001)
        return
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


@app.websocket("/ws/status")
async def ws_status(ws: WebSocket, token: Optional[str] = None):
    """
    Sistem durumu akışı — dashboard için 1 sn aralıkla QoD/event/bant bilgisi.

    Auth aktifse `?token=<JWT>` query param ile bağlanın.
    İstemci bağlanır, sunucu her saniye JSON yayınlar:
      { ts, qod_mode, bandwidth_mbps, event_count, ws_connections,
        bandwidth_efficiency, uptime_s }
    """
    if not _ws_auth_ok(token):
        await ws.close(code=4001)
        return
    await ws.accept()
    ws_active_connections.labels(endpoint="status").inc()
    try:
        while True:
            qod_st = state.qod.status()
            payload = {
                "ts": time.time(),
                "qod_mode": qod_st.mode,
                "bandwidth_mbps": qod_st.bandwidth_mbps,
                "active_session_id": qod_st.active_session_id,
                "event_count": state.store.count(),
                "ws_connections": len(state.subscribers),
                "bandwidth_efficiency": state.qod.bandwidth_efficiency(),
                "uptime_s": round(time.time() - _start_time, 1),
            }
            await ws.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    finally:
        ws_active_connections.labels(endpoint="status").dec()


# ──────────────────────────────────────────────────────────────────────────────
# Statik dosyalar
# ──────────────────────────────────────────────────────────────────────────────

_output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
os.makedirs(_output_dir, exist_ok=True)
app.mount("/output", StaticFiles(directory=_output_dir), name="output")

_frontend = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
