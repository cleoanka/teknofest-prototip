# Backend API Kolunun Çalışma Kuralları

> Bu belge backend/API kolunda çalışan geliştirici için bağlayıcı kurallardır.
> Kural ihlalleri diğer kolları kırar — önce oku, sonra yaz.

---

## Bu Kolun Sorumluluğu

Backend kolu şunları üretir:
- REST API endpoint'leri (`/api/*`, `/camara/*`)
- WebSocket bağlantı noktaları (`/ws/*`)
- SQLite olay deposu (EventStore)
- CAMARA QoD + Number Verification (mock → gerçek geçiş hazır)
- JWT RS256 kimlik doğrulama
- Prometheus metrics endpoint

**Bu kolun kapsamı dışında:** YZ modelleri, eğitim kodları, frontend/mobile.

---

## Değişmez Kurallar

### K1 — Şema Kontratı Kırılmaz
`ai/schema.py` içindeki `FrameResult`, `EventRecord`, `QoDStatus` şemaları
Backend ile YZ arasındaki kontrat. Bu şemaya alan **ekleyebilirsin** (geriye uyumlu),
ama mevcut alan adı/tipini değiştirme. Değişiklik gerekirse YZ kolundan onay al.

### K2 — Test Yeşil Kalır
`make test` her zaman yeşil olmalı. PR açmadan önce:
```bash
AI_MODE=mock .venv/bin/python -m pytest
```
Kırmızı test bırakma. Mock modunda (AI_MODE=mock) hiçbir model indirilmez.

### K3 — Config-First
Hiçbir eşik, sabit ya da URL koda gömülmez. Tüm değerler `config/settings.py`'den
gelir ve `.env` dosyasıyla override edilebilir. Magic number yasak.

### K4 — SQL Injection Yok
`backend/db.py`'deki tüm sorgular parametreli (`?` placeholder). String birleştirme
ile SQL oluşturma yasak.

### K5 — Endpoint Sözleşmesi
Her yeni endpoint:
1. Pydantic response model ile dönüş tipi tanımlanmış olmalı
2. Hata durumunda `HTTPException` ile anlamlı mesaj vermeli
3. Rate limit dekoratörü olan (`@limiter.limit`) olmalı
4. Swagger dokümantasyonu için docstring içermeli

### K6 — JWT Kontrol
`/api/*` endpoint'leri `require_auth` dependency'sini kullanır.
`REQUIRE_AUTH=false` (varsayılan) production'da `REQUIRE_AUTH=true` olmalı.
Test sırasında zorla false bırak — her test token almak zorunda kalmasın.

### K7 — WS Frame Boyutu
`/ws/ingest`'e gelen her mesaj 5 MB üstüyse `{"error": "frame too large"}` döner,
bağlantı kesilmez. Limit `config/settings.py` `ws_max_frame_bytes` field'ından okunur.

---

## Dosya Sorumlulukları

| Dosya | Ne İçerir | Değiştirme Sıklığı |
|---|---|---|
| `main.py` | Tüm endpoint'ler, AppState, lifespan | Sık |
| `db.py` | EventStore CRUD + sorgular | Orta |
| `auth.py` | JWTManager, require_auth dep. | Nadir |
| `metrics.py` | Prometheus counter/gauge/hist | Nadir |
| `frames.py` | JPEG↔numpy dönüşüm | Nadir |
| `qod_manager.py` | QoD tetik köprüsü | Nadir |
| `camara/qod.py` | Mock QoD provider | Turkcell gelince |
| `camara/number_verification.py` | Mock NumVerif | Turkcell gelince |

---

## Yeni Endpoint Ekleme Şablonu

```python
@app.get("/api/yeni-endpoint", tags=["api"])
@limiter.limit(f"{settings.rate_limit}/minute")
async def yeni_endpoint(
    request: Request,
    param: int = Query(default=50, ge=1, le=1000),
    _auth: dict | None = Depends(require_auth),
) -> dict:
    """Endpoint açıklaması — Swagger'da görünür."""
    ...
    return {"result": ...}
```

---

## Test Yazma Kuralları

- Her yeni endpoint için en az 3 test: başarılı yol, hatalı input, edge case
- `tests/conftest.py`'deki `client` fixture'ı kullan (AI_MODE=mock, :memory: DB)
- Rate limit testlerinde `slowapi`'nin test modu kullanılır (limiti bypass)
- JWT testlerinde `backend/auth.py`'deki `get_jwt_manager()` kullan

---

## API Versiyonlama Notu

Şu an versiyonsuz API (`/api/events`). Şartname değişirse:
- Header tabanlı versiyonlama: `X-API-Version: 1`
- Path tabanlı değil (`/v1/api/events`) — mobil kodu kırılır

---

## Performans Referansları

| Metrik | Hedef | Ölçüm Yeri |
|---|---|---|
| Uçtan uca gecikme | < 150 ms (Normal mod) | `total_latency_ms` |
| Inference gecikme | < 100 ms (Normal mod) | `latency_ms` (pipeline) |
| HTTP endpoint yanıt | < 50 ms (p99) | `/metrics` → `http_request_duration` |
| WS broadcast gecikme | < 10 ms | AppState.broadcast |

---

## Sık Yapılan Hatalar

**"Request has no attribute 'state'"**
→ `limiter` app.state'e eklenmemiş. `app.state.limiter = limiter` kontrol et.

**"JWT decode error: Signature verification failed"**
→ JWTManager singleton farklı instance'tan üretildi. `get_jwt_manager()` tek entry point.

**"422 Unprocessable Entity"**
→ Pydantic validation hatası. Request body/query param tipi yanlış.

**"429 Too Many Requests" test'lerde**
→ Test istemcisi rate limit'e takılıyor. `app.state.limiter` test'te reset edilmeli.
