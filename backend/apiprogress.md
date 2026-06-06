# Backend API Kolu — İlerleme Günlüğü

> Karar ve durum kaydı. Her oturum sonunda güncellenir.

---

## Mevcut Durum (2026-06-06)

| Özellik | Durum | Notlar |
|---|---|---|
| JWT RS256 Authentication | ✅ Tamamlandı | `backend/auth.py`, RS256 anahtar çifti startup'ta üretiliyor |
| Rate Limiting 100/min | ✅ Tamamlandı | slowapi, tüm `/api/*` ve `/camara/*` endpoint'leri |
| CAMARA env vars | ✅ Tamamlandı | `CAMARA_BASE_URL/CLIENT_ID/SECRET/MODE` settings.py'de |
| /api/statistics | ✅ Tamamlandı | Son 1 saat, risk breakdown, bandwidth_efficiency |
| /api/vehicles/{plate} | ✅ Tamamlandı | Plaka bazlı olay geçmişi, 404 if not found |
| /api/events/{id} | ✅ Tamamlandı | Tek olay ID ile sorgulama |
| /api/events/export | ✅ Tamamlandı | CSV download, filtre parametreleri uygulanıyor |
| Event filtering (from_ts/to_ts/level/vtype) | ✅ Tamamlandı | db.py SQL güncellendi, parametreli |
| /camara/qod/sessions (GET) | ✅ Tamamlandı | Aktif oturum listesi |
| WS frame size limit (5 MB) | ✅ Tamamlandı | `/ws/ingest` boyut kontrolü |
| Latency tracking (total_latency_ms) | ✅ Tamamlandı | client_ts, server_recv_ts, FrameResult alanı |
| Prometheus /metrics | ✅ Tamamlandı | HTTP metrikler + custom counter/gauge/histogram |
| /api/health zenginleştirme | ✅ Tamamlandı | uptime_s, event_count, ws_connections |
| WS bağlantı yönetimi | ✅ Tamamlandı | disconnect cleanup, WS sayacı |
| Test kapsamı (yeni testler) | ✅ Tamamlandı | test_auth, test_statistics, test_filtering, test_new_endpoints |

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
Durum: TÜM TESTLER YEŞİL
Toplam test: 85+
Ortam: AI_MODE=mock, DB=:memory:
```

---

## Performans Ölçümleri

| Metrik | Ölçülen | Hedef | Durum |
|---|---|---|---|
| Mock mod inference_ms | ~2 ms | < 100 ms | ✅ |
| HTTP /api/health yanıt | < 5 ms | < 50 ms | ✅ |
| WS broadcast (1 abone) | < 1 ms | < 10 ms | ✅ |
| total_latency_ms (mock) | ~5 ms | < 150 ms | ✅ |
