# Backend API Geliştirme Planı

> TEKNOFEST 2026 · 5G & YZ Akıllı Yol Güvenliği — Backend/API Kolunun Eksiksiz Yol Haritası
> Son güncelleme: 2026-06-06 (v1.4.0 — 233 test ✅)

---

## Strateji

Backend kolunun tek sorumluluğu var: **şartname gereksinimlerini karşılayan, ölçülebilir, test edilebilir bir API**. YZ modelleri, mobil uygulama ya da frontend bu planın dışında. Her özellik yarışma değerlendirmesine doğrudan katkı sağlamalı.

---

## Faz 1 — Temel Güvenlik & Altyapı (ÖTR Zorunlusu)

### F1.1 JWT RS256 Kimlik Doğrulama
**ÖTR:** "JWT RS256 + TLS 1.3 + 100 req/dak limit"

- [x] `backend/auth.py` — JWTManager sınıfı (RS256 anahtar çifti, issue, verify)
- [x] `MockNumberVerification.issue_token()` → gerçek RS256 JWT döner
- [x] `require_auth` FastAPI dependency — Bearer token doğrulama
- [x] `/api/*` endpoint'lerinde opsiyonel auth (REQUIRE_AUTH=true ile zorunlu)
- [x] `REQUIRE_AUTH`, `JWT_TTL_S` settings.py'e eklendi

**Doğrulama:** POST /camara/number-verification:verify → token al → /api/events Authorization header ile

### F1.2 Rate Limiting (100 req/dak)
**ÖTR:** "100 req/dak limit"

- [x] `slowapi` tabanlı `Limiter` → AppState'te singleton
- [x] Tüm `/api/*` ve `/camara/*` endpoint'lerinde `@limiter.limit("100/minute")`
- [x] 429 yanıt formatı standartlaştırıldı
- [x] `RATE_LIMIT` settings.py'e eklendi (varsayılan 100/minute)

### F1.3 CAMARA Geçiş Altyapısı
**Hedef:** Turkcell sandbox erişimi geldiğinde .env değiştirmek yeterli olsun

- [x] `CAMARA_BASE_URL`, `CAMARA_CLIENT_ID`, `CAMARA_CLIENT_SECRET`, `CAMARA_MODE` (mock|real) settings.py'e eklendi
- [x] Tüm CAMARA konfigürasyonu tek yerden okunuyor

---

## Faz 2 — API Zenginleştirme (Şartname Kapsamı)

### F2.1 /api/statistics Endpoint'i
**Hedef:** Jüri için anlık sistem performansı kanıtı

- [x] Son 1 saatin olay sayısı
- [x] High-risk (score ≥ 60) count
- [x] Average speed (km/h)
- [x] Risk seviyesi dağılımı (LOW/MEDIUM/HIGH/CRITICAL breakdown)
- [x] QoD tetik sayısı (critical_cycles)
- [x] Bant genişliği verimliliği (bandwidth_efficiency)
- [x] Prometheus'a da besleniyor

### F2.2 /api/vehicles/{plate} Endpoint'i
**Hedef:** Plaka bazlı olay geçmişi — mobil dashboard detay sayfası

- [x] Plaka parametresi path'te
- [x] Tüm olaylar tarih sıralı (DESC)
- [x] 404 — plaka hiç görülmediyse
- [x] TR plaka format doğrulaması

### F2.3 Event Filtreleme Parametreleri
**Hedef:** /api/events zengin sorgulama

- [x] `from_ts` — başlangıç timestamp (epoch saniye)
- [x] `to_ts` — bitiş timestamp
- [x] `level` — risk seviyesi filtresi (LOW|MEDIUM|HIGH|CRITICAL)
- [x] `vtype` — araç tipi filtresi (car|truck|bus...)
- [x] `db.py` SQL sorgusu güncellendi (parametreli, injection-safe)

### F2.4 /api/events/{id} Endpoint'i
**Hedef:** Tek olay detayı

- [x] ID ile tek olay sorgulama
- [x] 404 — bulunamazsa
- [x] EventRecord tam detay döner

### F2.5 /api/events/export Endpoint'i
**Hedef:** CSV export — jüri değerlendirmesi için ham veri

- [x] Tüm olayları CSV formatında indir
- [x] `Content-Disposition: attachment; filename=events.csv`
- [x] Filtreleme parametreleri export'a da uygulanıyor

### F2.6 /camara/qod/sessions (GET)
**Hedef:** Aktif QoD oturumlarını listele — CAMARA spec tamamlama

- [x] Aktif oturum listesi
- [x] Her oturum: id, device, qos_profile, requested_mbps, age_s, status

---

## Faz 3 — Gecikme Ölçümü & Kanıtlama

### F3.1 Uçtan Uca Gecikme Takibi
**ÖTR exit criterion:** Normal modda < 150 ms uçtan uca gecikme

- [x] `FrameResult.total_latency_ms` alanı eklendi
- [x] WS ingest'te `client_ts` okuma (istemci gönderim zamanı)
- [x] `server_recv_ts` kayıt, inference sonrası `total_latency_ms` hesap
- [x] `inference_ms` (sadece YZ) ayrı, `total_latency_ms` (ağ+YZ) ayrı
- [x] Prometheus histogram: `frame_inference_duration_seconds`

---

## Faz 4 — Observability (Prometheus Metrics)

### F4.1 /metrics Endpoint'i
**Hedef:** Grafana entegrasyonu için metrik sunumu

- [x] `prometheus-fastapi-instrumentator` → otomatik HTTP metrikler
- [x] Custom counter: `qod_sessions_created_total`
- [x] Custom counter: `events_recorded_total`  
- [x] Custom gauge: `ws_active_connections`
- [x] Custom histogram: `frame_inference_ms` (buckets: 10,25,50,100,150,300 ms)

---

## Faz 5 — WebSocket Sağlamlaştırma

### F5.1 Frame Size Limiti
- [x] `/ws/ingest`'te max 5 MB frame size kontrolü
- [x] Aşılırsa `{"error": "frame too large"}` yanıtı

### F5.2 Bağlantı Yönetimi
- [x] `/ws/detections` disconnect'te subscriber set'ten anında temizleme
- [x] WS bağlantı sayısı metric'e yansıtılıyor

---

## Faz 6 — Sağlık & Sistem Bilgisi

### F6.1 /api/health Zenginleştirme
- [x] `uptime_s` — sunucu çalışma süresi
- [x] `event_count` — toplam kayıtlı olay
- [x] `ws_connections` — aktif WS bağlantı sayısı

### F6.2 /api/health/deep
- [x] DB bağlantı testi (count sorgusu)
- [x] QoD motor durumu kontrolü
- [x] Bellek kullanımı (psutil varsa)
- [x] 503 degraded modda

---

## Faz 7 — Gelişmiş API Özellikleri (v1.3–v1.4)

### F7.1 Güvenlik & İzleme Middleware
- [x] GZip sıkıştırma (minimum_size=500)
- [x] X-Content-Type-Options, X-Frame-Options, X-XSS-Protection
- [x] X-Request-ID (istemci değeri yankılanır veya UUID üretilir)
- [x] X-Response-Time (milisaniye cinsinden)

### F7.2 WebSocket Token Auth
- [x] `?token=<JWT>` query param — tüm WS endpoint'leri
- [x] REQUIRE_AUTH=true ile invalid token → close(4001)

### F7.3 Pagination & Sıralama
- [x] `/api/events?offset=N` — OFFSET pagination
- [x] `/api/events?sort_by=ts|risk_score|speed_kmh|id&sort_dir=asc|desc`
- [x] `/api/vehicles?offset=N` — araç listesi pagination
- [x] X-Total-Count, X-Filtered-Count, X-Offset response headers
- [x] db.count_filtered() — doğru toplam için ayrı COUNT sorgusu

### F7.4 Demo & Geliştirici Kolaylıkları
- [x] `POST /api/demo-token` — require_auth=False modda hızlı JWT
- [x] `POST /api/events/test` — demo için test olay enjeksiyonu
- [x] OpenAPI tag açıklamaları (7 kategori)
- [x] Swagger UI özelleştirme (tryItOut, filter, persistAuth)

### F7.5 Analitik Endpoint'ler
- [x] `/api/qod/proof` — ÖTR %40 bant verimliliği kanıtı (10 alan)
- [x] `/api/events/heatmap` — zaman×risk_level 2D matris
- [x] `/api/vehicles/{plate}/timeline` — saatlik risk zaman serisi
- [x] `/api/version` — Python/platform/ai_mode/build bilgisi
- [x] `/api/ping` — ultralight gecikme ölçümü

### F7.6 Tam CRUD
- [x] `DELETE /api/events` — filtreli toplu silme (confirm=true)
- [x] `DELETE /api/events/{id}` — tek olay silme
- [x] `/api/events?plate=` — kısmi eşleşme arama

### F7.7 Yapılandırılmış Loglama
- [x] JSON formatter — her satır geçerli JSON
- [x] uvicorn logları da JSON handler'a yönlendirildi

---

## Test Kapsamı

| Test Dosyası | Kapsam |
|---|---|
| `tests/test_auth.py` | JWT üretim, doğrulama, expire, geçersiz token |
| `tests/test_statistics.py` | /api/statistics doğruluğu |
| `tests/test_filtering.py` | from_ts, to_ts, level, vtype filtreleme |
| `tests/test_new_endpoints.py` | /vehicles/{plate}, /events/{id}, /events/export, /qod/sessions |
| `tests/test_rate_limit.py` | 429 response, limit davranışı |
| `tests/test_latency.py` | total_latency_ms hesabı, client_ts |
| `tests/test_metrics.py` | /metrics endpoint erişilebilirlik |

---

## Öncelik Sırası

```
F1.1 JWT RS256         ← ÖTR zorunlusu, güvenlik
F1.2 Rate Limiting     ← ÖTR zorunlusu, güvenlik
F1.3 CAMARA env vars   ← Geçiş kolaylığı
F2.x API endpointler   ← Değerlendirici için içerik
F3.1 Latency tracking  ← < 150 ms exit criterion kanıtı
F4.1 Prometheus        ← Grafana görselleştirme
F5.x WS sağlamlaştırma ← Production kalitesi
F6.1 Health zenginleşt ← İzlenebilirlik
```

---

## Mock → Gerçek Geçiş Kontrol Listesi

Turkcell erişimi geldiğinde sadece şunları değiştir:

```env
CAMARA_MODE=real
CAMARA_BASE_URL=https://opengateway.turkcell.com.tr
CAMARA_CLIENT_ID=<prod_client_id>
CAMARA_CLIENT_SECRET=<prod_secret>
```

Kod değişikliği gerekmez — `backend/camara/qod.py` ve `number_verification.py` bu
değişkenlere göre real adaptör kullanacak şekilde hazır.
