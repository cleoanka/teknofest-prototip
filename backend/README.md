# Backend API — RoadGuard

**TEKNOFEST 2026 · 5G & Yapay Zeka ile Akıllı Yol Güvenliği**

FastAPI v1.5 tabanlı REST + WebSocket sunucusu. YZ çıkarım hattını yönetir, CAMARA 5G QoD
API'siyle iletişim kurar ve tüm sonuçları mobil/web istemcilerine yayınlar.

---

## Hızlı Başlangıç

```bash
# macOS / Linux
./run_dev.sh start        # arka planda başlat
./run_dev.sh logs         # canlı loglar

# Windows PowerShell
.\run_dev.ps1 start

# Manuel (geliştirme)
AI_MODE=mock .venv/bin/python -m uvicorn backend.main:app --reload --port 8000

# Swagger UI
open http://localhost:8000/docs
```

Gerçek YZ modeli için (GPU):
```bash
pip install ultralytics easyocr mediapipe huggingface_hub
AI_MODE=real uvicorn backend.main:app
```

---

## Mimari Genel Bakış

```
İstemci (Mobil / Web)
    │  REST  /  WebSocket
    ▼
backend/main.py  ─── AppState ─┬── Pipeline (ai/)
    │                           ├── QoDManager → camara/qod.py
    │                           ├── EventStore → db.py (SQLite)
    │                           └── MockNumberVerification
    │
    ├── /ws/ingest      ← kare al → pipeline → broadcast
    ├── /ws/detections  ← subscribe (salt-okuma)
    ├── /ws/status      ← sistem durumu (1 s aralık)
    │
    ├── auth.py         JWT RS256 (startup'ta anahtar üretimi)
    ├── metrics.py      Prometheus counter/gauge/histogram
    └── frames.py       base64/JPEG → numpy BGR
```

**Temel tasarım:** Her WebSocket `/ws/ingest` çerçevesi → `Pipeline.process()` → `FrameResult`
JSON → `/ws/detections` abonelerine yayın. Risk skoru ≥ 30 olan olaylar SQLite'a kaydedilir.
QoD tetik motoru (`ai/qod_trigger.py`) A–E koşul kararını verir; `qod_manager.py` bunu
CAMARA API çağrısına çevirir.

---

## Uç Noktalar (v1.5)

### Sistem

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/api/health` | GET | Durum, uptime, AI modu, WS bağlantı sayısı, event sayısı |
| `/api/health/deep` | GET | Alt sistem kontrolleri (DB, QoD, bellek); degraded → 503 |
| `/api/ping` | GET | Ultra-hızlı gecikme testi — yalnızca epoch timestamp döner |
| `/api/version` | GET | Python versiyonu, platform, ai_mode, camara_mode, uptime |
| `/api/system/info` | GET | psutil: RSS/VMS bellek, CPU, thread sayısı, disk |

### Olaylar

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/api/events` | GET | Riskli olay listesi — `from_ts`, `to_ts`, `level`, `vtype`, `plate`, `min_score`, `sort_by`, `sort_dir`, `limit`, `offset` parametreleri |
| `/api/events/summary` | GET | Saatlik olay dağılımı — `hours` parametresi (1–168) |
| `/api/events/export` | GET | CSV indirme — tüm filtre parametreleri uygulanır |
| `/api/events/heatmap` | GET | Zaman×risk_level 2D matris — grafik için |
| `/api/events/test` | POST | Demo olay enjeksiyonu — `count`, `risk_level`, `plate_prefix` |
| `/api/events/{id}` | GET | Tek olay detayı |
| `/api/events/{id}` | DELETE | Tek olay sil (404 koruması) |
| `/api/events` | DELETE | Toplu sil — `confirm=true` zorunlu + filtre parametreleri |
| `/api/clear` | POST | Tüm veritabanını sıfırla |

**Sorgu parametreleri (GET /api/events):**
```
from_ts     float   Unix timestamp başlangıç
to_ts       float   Unix timestamp bitiş
level       str     LOW | MEDIUM | HIGH | CRITICAL
vtype       str     car | truck | bus | motorcycle
plate       str     kısmi LIKE sorgusu (büyük/küçük harf duyarsız)
min_score   int     minimum risk skoru (varsayılan 0)
sort_by     str     ts | risk_score | speed_kmh | id
sort_dir    str     asc | desc
limit       int     sayfa boyutu
offset      int     sayfalama ofseti
```

**Yanıt başlıkları:**
```
X-Total-Count      toplam sonuç sayısı
X-Filtered-Count   filtre uygulandıktan sonra
X-Offset           mevcut ofset
```

### Araçlar

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/api/vehicles` | GET | Plaka bazlı araç özeti — `offset`, `limit` parametreleri; `X-Total-Count` header |
| `/api/vehicles/{plate}` | GET | Plakaya göre olay geçmişi (TR plaka format doğrulaması) |
| `/api/vehicles/{plate}/timeline` | GET | Saatlik risk zaman serisi — `avg_speed`, `max_risk`, `risk_levels` |

### Analitik & QoD

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/api/statistics` | GET | Son N saatin özeti — `hours` parametresi; risk dağılımı, hız ortalaması, `bandwidth_efficiency` |
| `/api/qod/status` | GET | Anlık bant durumu + `bandwidth_efficiency` oranı |
| `/api/qod/proof` | GET | ÖTR %40 kriter kanıtı — jüri için tetik istatistikleri raporu |

### Ayarlar & Auth

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/api/settings` | GET | Çalışma zamanı ayarları (hassas bilgiler hariç) |
| `/api/settings` | PATCH | Runtime güncelleme — `ai_mode`, QoD eşikleri vb. |
| `/api/demo-token` | POST | Geliştirme JWT token'ı (`require_auth=false` modda) |
| `/.well-known/jwks.json` | GET | RS256 public key — JWKS formatında |

### Video Test

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/api/test-video` | POST | Video dosyasını YZ'den geçir — `filename`, `every_n`, `scale` |
| `/api/test-video/files` | GET | Mevcut test videoları listesi |

### CAMARA

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/camara/number-verification:verify` | POST | Sessiz SIM doğrulama → RS256 JWT döner |
| `/camara/qod/sessions` | GET | Aktif QoD oturum listesi |
| `/camara/qod/sessions` | POST | QoD oturumu aç (20 Mbps, 5 s) |
| `/camara/qod/sessions/{sid}` | GET | Oturum detayı |
| `/camara/qod/sessions/{sid}` | DELETE | Oturumu kapat → bant 5 Mbps'e döner |

### İzleme & WebSocket

| Uç Nokta | Yöntem | Açıklama |
|---|---|---|
| `/metrics` | GET | Prometheus metrikleri (Grafana entegrasyonu) |
| `/ws/ingest` | WS | Kare gönder → FrameResult al (`client_ts` destekli) |
| `/ws/detections` | WS | Salt-okuma abone soketi — web/mobil izleme |
| `/ws/status` | WS | Sistem durum akışı (1 sn aralık) |

> **Rate limit:** Tüm `/api/*` ve `/camara/*` → **100 req/dak/IP** (slowapi).
> **Auth:** `Authorization: Bearer <JWT>` — `REQUIRE_AUTH=false` varsayılan; `true` ile zorunlu.

---

## WebSocket Protokolü

### `/ws/ingest` — Kare Gönderimi

**İstemci → Sunucu (JSON):**
```json
{
  "frame": "<base64 JPEG veya data:image/jpeg;base64,...>",
  "critical": false,
  "client_ts": 1717750000.123,
  "fps": 30.0
}
```

**Sunucu → İstemci (FrameResult JSON, < 3 KB):**
```json
{
  "frame_id": 42,
  "ts": 1717750000.456,
  "mode": "CRITICAL",
  "model_profile": "yolov8s",
  "detections": [...],
  "vehicle": {
    "present": true,
    "track_id": 1,
    "plate": {"text": "34TC8532", "confidence": 0.956, "valid_format": true},
    "speed_kmh": 48.2,
    "speed_is_calibrated": true,
    "plate_bbox": {"x1": 210, "y1": 380, "x2": 460, "y2": 445},
    "plate_pixel_width": 250.0,
    "color": "beyaz",
    "vtype": "car"
  },
  "driver": {"fatigue": false, "phone_use": false, "smoking": false},
  "risk": {"score": 35, "level": "MEDIUM", "factors": ["overspeed"]},
  "latency_ms": 52.3,
  "total_latency_ms": 89.1,
  "fps": 19.2
}
```

### `/ws/status` — Sistem Durumu

Her 1 saniyede yayınlanır:
```json
{
  "uptime_s": 3600,
  "ai_mode": "real",
  "ws_connections": 2,
  "event_count": 17,
  "qod": {"mode": "NORMAL", "bandwidth_mbps": 5, "bandwidth_efficiency": 0.82}
}
```

---

## Kimlik Doğrulama

JWT RS256 tabanlı. Startup'ta RSA anahtar çifti üretilir (veya `JWT_PRIVATE_KEY_PATH` ile diskten yüklenir).

```bash
# Token al (require_auth=false modda demo-token kullan)
TOKEN=$(curl -s -X POST http://localhost:8000/api/demo-token | jq -r .access_token)

# Korumalı endpoint'e eriş
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/events

# Public key (JWKS)
curl http://localhost:8000/.well-known/jwks.json
```

**Ortam değişkenleri:**
```bash
REQUIRE_AUTH=true          # Bearer token zorunlu (varsayılan: false)
JWT_TTL_S=3600             # Token geçerlilik süresi (saniye)
JWT_PRIVATE_KEY_PATH=      # PEM dosyası — boşsa her startup yeni anahtar üretir
```

---

## Yapılandırma

`config/settings.py` veya `.env` dosyası:

```bash
# YZ
AI_MODE=auto               # real | mock | auto
YOLO_DEVICE=auto           # auto | cpu | mps | cuda
CONF_NORMAL=0.35
CONF_CRITICAL=0.25

# Plaka
LP_AUTO_DOWNLOAD=true      # false ile oto-indirme kapat
LP_MODEL_PATH=             # yerel .pt yolu (öncelik 1)
LP_MOCK=false              # true → CI/test için LP atla

# QoD tetik eşikleri
QOD_EVAL_PERIOD_MS=500
QOD_BBOX_GROWTH_THRESHOLD=0.18
QOD_LOW_CONF_THRESHOLD=0.55
QOD_OCR_CONF_THRESHOLD=0.75
QOD_MAX_SESSION_S=5.0

# CAMARA
CAMARA_MODE=mock           # real için Turkcell sandbox
CAMARA_BASE_URL=
CAMARA_CLIENT_ID=
CAMARA_CLIENT_SECRET=

# Hız
SPEED_LIMIT_KMH=50.0
SPEED_CALIBRATION_K=900.0

# Sunucu
HOST=0.0.0.0
PORT=8000
DB_PATH=events.sqlite3
RATE_LIMIT=100             # req/dak/IP
```

---

## Modüller

| Dosya | Görev |
|---|---|
| `main.py` | Tüm REST + WebSocket uç noktaları (v1.5), `AppState`, `QoDManager` orkestrasyon |
| `auth.py` | JWT RS256 — anahtar üretimi/yükleme, `require_auth` dependency, JWKS endpoint |
| `metrics.py` | Prometheus domain metrikleri: `qod_sessions_total`, `frame_inference_ms`, `ws_active_connections`, `events_recorded_total` |
| `qod_manager.py` | `ai/qod_trigger.py` tetik kararı → CAMARA API köprüsü |
| `db.py` | SQLite `EventStore` — CRUD, filtreleme, sayfalama, timeline, heatmap |
| `frames.py` | `base64` / `data:image/...` → numpy BGR çözücü (JPEG/PNG) |
| `camara/qod.py` | Mock CAMARA QoD API — gerçek Turkcell sandboxuyla değiştirilecek |
| `camara/number_verification.py` | Mock CAMARA Number Verification — sessiz SIM doğrulama |

---

## Prometheus Metrikleri

`/metrics` endpoint'i Grafana ile kullanılabilir:

```
# Özel metrikler
roadguard_events_recorded_total        Kaydedilen riskli olay sayısı
roadguard_qod_sessions_total           Açılan QoD oturumu sayısı
roadguard_ws_active_connections        Anlık WS bağlantı sayısı
roadguard_frame_inference_ms           YZ pipeline süresi (histogram, ms)
roadguard_frame_total_latency_ms       Uçtan uca gecikme (ağ dahil, ms)

# FastAPI otomatik
http_requests_total{method, handler, status}
http_request_duration_seconds{...}
```

---

## Güvenlik Başlıkları

Her yanıtta otomatik:
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
X-Request-ID: <uuid>          istemci başlığı yankılanır veya sunucu üretir
X-Response-Time: <ms>         işlem süresi
```

GZip sıkıştırma: 500 bayt üzeri yanıtlar otomatik sıkıştırılır.

---

## Testler

```bash
# Tüm testler (mock modda — model/GPU gerektirmez)
AI_MODE=mock LP_MOCK=true pytest -q

# Backend'e özel
pytest tests/test_auth.py tests/test_events_api.py tests/test_v15_features.py -v
```

**Test kapsamı (308 test, 27 dosya):**

| Dosya | Kapsam |
|---|---|
| `test_auth.py` | JWT RS256 üretim, doğrulama, expire, tamper koruması |
| `test_camara_*.py` | SIM doğrulama, QoD CRUD |
| `test_events_api.py` | EventStore CRUD, API |
| `test_filtering.py` | from_ts/to_ts/level/vtype/plate filtreleme |
| `test_v14_features.py` | health/deep, WS auth, JSON loglama |
| `test_v15_features.py` | CORS expose, system/info, qod/{sid}, export |
| `test_plate_tracker.py` | Araç-id'ye bağlı plaka kararlılığı |
| `test_plate_crop.py` | Likeness geçidi, refine crop, keskinlik |
| `test_middleware_and_proof.py` | GZip, güvenlik başlıkları, qod/proof |
| `test_ws_e2e.py` | WS ingest/detections/broadcast uçtan uca |

---

## Mock → Gerçek CAMARA Geçişi

```python
# config/settings.py veya .env
CAMARA_MODE=real
CAMARA_BASE_URL=https://api.sandbox.turkcell.com.tr
CAMARA_CLIENT_ID=<client_id>
CAMARA_CLIENT_SECRET=<secret>
```

`backend/camara/qod.py` ve `number_verification.py` dosyaları gerçek Turkcell sandbox
endpoint'leriyle aynı imzayı kullanır — sadece `CAMARA_MODE=real` set etmek yeterli.
`qod_manager.py` davranışı değişmez.

---

## Performans Referansları

| Metrik | Ölçülen | Hedef |
|---|---|---|
| Mock mod pipeline (inference) | ~2 ms | < 100 ms |
| Gerçek mod YOLOv8n (RTX 4070) | ~14 ms (~72 FPS) | < 40 ms |
| Gerçek mod pipeline MPS | ~50 ms med. | < 150 ms |
| HTTP /api/health yanıt | < 5 ms | < 50 ms |
| WS broadcast (1 abone) | < 1 ms | < 10 ms |
| total_latency_ms (uçtan uca, mock) | ~5 ms | < 150 ms |
| FrameResult JSON boyutu | < 1 KB | < 3 KB |
