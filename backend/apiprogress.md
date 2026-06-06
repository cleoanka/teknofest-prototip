# Backend API Kolu — İlerleme Günlüğü

> Karar ve durum kaydı. Her oturum sonunda güncellenir.

---

## Mevcut Durum (2026-06-06)

| Özellik | Durum | Notlar |
|---|---|---|
| JWT RS256 Authentication | ✅ | `backend/auth.py`, RS256 anahtar çifti startup'ta üretiliyor |
| JWT key kalıcılığı (PEM dosyası) | ✅ | JWT_PRIVATE_KEY_PATH, restart sonrası token geçerliliği |
| Rate Limiting 100/min | ✅ | slowapi, tüm `/api/*` ve `/camara/*` endpoint'leri |
| CAMARA env vars | ✅ | `CAMARA_BASE_URL/CLIENT_ID/SECRET/MODE` settings.py'de |
| /api/statistics | ✅ | Son N saat, risk breakdown, bandwidth_efficiency |
| /api/events/summary | ✅ | Saatlik dağılım, grafik için (1–168 saat) |
| /api/vehicles/{plate} | ✅ | Plaka bazlı olay geçmişi, TR plaka format validasyon |
| /api/events/{id} | ✅ | Tek olay ID ile sorgulama |
| /api/events/export | ✅ | CSV download, filtre parametreleri uygulanıyor |
| /api/events offset pagination | ✅ | `?offset=N` ile sayfalama, X-Offset + X-Filtered-Count header |
| Event filtering (from_ts/to_ts/level/vtype) | ✅ | db.py SQL güncellendi, parametreli |
| /api/settings (GET) | ✅ | Salt-okunur ayar görüntüleme, hassas bilgiler hariç |
| /api/settings (PATCH) | ✅ | Runtime QoD eşik güncelleme, demo için |
| /.well-known/jwks.json | ✅ | RS256 public key PEM endpoint |
| /camara/qod/sessions (GET) | ✅ | Aktif oturum listesi |
| /api/qod/proof | ✅ | ÖTR %40 bant verimliliği kriteri kanıtı — jüri için |
| WS /ws/ingest frame size limit (5 MB) | ✅ | Boyut kontrolü |
| WS /ws/detections | ✅ | disconnect cleanup, WS sayacı |
| WS /ws/status | ✅ | 1 sn aralıkla sistem durumu akışı |
| Latency tracking (total_latency_ms) | ✅ | client_ts, server_recv_ts, FrameResult alanı |
| Prometheus /metrics | ✅ | HTTP metrikler + custom counter/gauge/histogram |
| /api/health zenginleştirme | ✅ | uptime_s, event_count, ws_connections |
| GZip middleware | ✅ | minimum_size=500 bayt, büyük yanıtlar otomatik sıkıştırılır |
| Güvenlik başlıkları | ✅ | X-Content-Type-Options, X-Frame-Options, X-XSS-Protection |
| X-Request-ID izleme | ✅ | İstemci başlığı yankılanır veya sunucu UUID üretir |
| X-Response-Time header | ✅ | Her yanıtta milisaniye cinsinden yanıt süresi |
| WS token auth (`?token=`) | ✅ | require_auth=True ile WS bağlantıları JWT doğrulama ister |
| /api/health/deep | ✅ | DB, QoD, bellek alt sistem kontrolleri; 503 degraded modda |
| JSON loglama | ✅ | `_JsonFormatter` — her log satırı tek JSON satırı; prod için |
| OpenAPI tag açıklamaları | ✅ | system/events/vehicles/analytics/camara/auth/tools |
| Swagger UI özelleştirme | ✅ | tryItOutEnabled, filter, persistAuthorization, tag gizleme |

---

## Karar Günlüğü

### 2026-06-06 — JWT Manager Singleton

**Karar:** `JWTManager` modül seviyesinde singleton (`get_jwt_manager()`).
**Sebep:** FastAPI dependency sistemi içinde `AppState`'e bağımlılık yaratan
circular import sorununu önlemek. Anahtar çifti startup'ta tek sefer üretiliyor,
tüm request lifecycle boyunca aynı public key kullanılıyor.
**Alternatif düşünüldü:** AppState içinde JWTManager → test izolasyonu güçleşir.

### 2026-06-06 — Rate Limiting Yaklaşımı

**Karar:** `slowapi` + her endpoint'e `@limiter.limit()` dekoratörü.
**Sebep:** ÖTR'nin "100 req/dak" gereksinimi endpoint bazlı kontrol gerektiriyor.
Middleware tabanlı yaklaşım WS bağlantılarını da sınırlardı (istenmeyen).
**Uygulama notu:** Test ortamında limiter aktif ama 100/minute limit
normal test çalışmasında aşılmıyor.

### 2026-06-06 — REQUIRE_AUTH Varsayılan = False

**Karar:** `REQUIRE_AUTH` varsayılan olarak `false`.
**Sebep:** Mevcut 73 test token almadan çalışıyor. Production'da `.env` ile `true` yap.
Değerlendirici test yaparken swagger UI'dan token alıp `Authorize` butonuna yapıştırabilir.

### 2026-06-06 — prometheus-fastapi-instrumentator v6.1.0

**Karar:** v6.x kullanıldı, v8.x değil.
**Sebep:** v8.x starlette>=1.0.0 gerektiriyor, fastapi 0.115.6 starlette<0.42.0 istiyor.
Uyumluluk kırılmasın diye v6.1.0 pinlendi. `requirements.txt` güncellendi.

### 2026-06-06 — CSV Export

**Karar:** `/api/events/export` endpoint'i eklendi.
**Sebep:** Yarışma jürisi ham veriyi görmek isteyebilir. CSV formatı evrensel.
Filtre parametrelerini destekliyor (from_ts, to_ts, level, vtype).

---

## Bekleyen İşler (Sonraki Sprint)

| Görev | Öncelik | Bağımlılık |
|---|---|---|
| PostgreSQL + asyncpg geçişi | Orta | DevOps kurulumu |
| Redis Streams event bus | Orta | Redis kurulumu |
| TorchServe inference proxy | Düşük | Model deployment |
| Mock → Real CAMARA swap | Kritik | Turkcell sandbox erişimi |
| JWT key dosyadan yükleme (prod) | Orta | Secret management |
| WS multi-worker (Redis Pub/Sub) | Orta | Redis kurulumu |

---

## Test Sonuçları

```
Son çalıştırma: 2026-06-06
Durum: TÜM TESTLER YEŞİL ✅
Toplam test: 181 (73 eski → 181 yeni)
Ortam: AI_MODE=mock, DB=:memory:
```

| Test Dosyası | Test Sayısı | Kapsam |
|---|---|---|
| test_auth.py | 8 | JWT RS256 üretim, doğrulama, expire, tamper |
| test_camara_numverif.py | 4 | SIM doğrulama, JWT entegrasyonu |
| test_camara_qod.py | 4 | QoD oturum create/delete/status |
| test_events_api.py | 4 | EventStore CRUD, API |
| test_filtering.py | 12 | from_ts/to_ts/level/vtype filtreleme |
| test_health.py | 2 | /api/health, /api/qod/status |
| test_latency.py | 5 | total_latency_ms, client_ts, WS frame limiti |
| test_middleware_and_proof.py | 18 | GZip, güvenlik başlıkları, qod/proof, offset pagination |
| test_new_endpoints.py | 18 | vehicles/{plate}, events/{id}, export, QoD list |
| test_patch_settings.py | 10 | Runtime settings, events/summary |
| test_pipeline_schema.py | 4 | FrameResult şema doğrulama |
| test_qod_trigger.py | 8 | A-E koşul motoru |
| test_risk.py | 4 | Risk skoru hesaplama |
| test_settings_and_auth.py | 12 | /api/settings, JWKS, plate validasyon, WS status |
| test_speed.py | 4 | Hız tahmini |
| test_statistics.py | 6 | /api/statistics doğruluğu |
| test_training_*.py | 35 | Eğitim/veri araçları |
| test_v14_features.py | 19 | health/deep, X-Response-Time, WS auth, OpenAPI, JSON log |
| test_ws_e2e.py | 4 | WS ingest/detections/broadcast uçtan uca |

---

## Performans Ölçümleri

| Metrik | Ölçülen | Hedef | Durum |
|---|---|---|---|
| Mock mod inference_ms | ~2 ms | < 100 ms | ✅ |
| HTTP /api/health yanıt | < 5 ms | < 50 ms | ✅ |
| WS broadcast (1 abone) | < 1 ms | < 10 ms | ✅ |
| total_latency_ms (mock) | ~5 ms | < 150 ms | ✅ |
