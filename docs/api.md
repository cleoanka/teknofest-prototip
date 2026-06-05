# API Kolu Rehberi — Backend & Sunucu Geliştirme

> Bu belge backend/API kolunda çalışanlar için yazıldı. FastAPI sunucusunu,
> WebSocket'i, CAMARA entegrasyonunu ve veritabanı katmanını açıklıyor.

---

## Sen Ne Yapacaksın?

API kolu projenin "omurgası"dır. Kameranın gönderdiği görüntüleri alır,
YZ'ye iletir, sonuçları ön yüze yollar ve her şeyi bir arada tutar.

Somut görevlerin:
- Backend sunucusunu çalışır durumda tutmak
- Yeni API uç noktaları eklemek (yarışma isterleri değişirse)
- CAMARA QoD/Number Verification entegrasyonunu geliştirmek
- Veritabanı sorgularını optimize etmek
- Sunucunun test edilmesini sağlamak

---

## Önce Bunları Öğren

1. **HTTP nasıl çalışır** — GET, POST, DELETE nedir, status code'lar ne anlama gelir
   - Kaynak: MDN Web Docs "HTTP" rehberi (Türkçe de var)

2. **Python async/await** — asenkron programlama nedir
   - FastAPI tamamen async tabanlı; `await` görmezden gelirsen her şey donar
   - Kaynak: "Python async tutorial" YouTube'da bol miktarda

3. **FastAPI giriş** — 30 dakika
   - [fastapi.tiangolo.com/tutorial](https://fastapi.tiangolo.com/tutorial/) — Türkçe dil seçeneği var
   - Sadece "First Steps" ve "Path Parameters" bölümü yeterli başlangıç için

4. **WebSocket kavramı** — ne olduğunu anlamak için
   - "WebSocket vs HTTP" araması yapman yeterli; 5 dakikalık bir okuma

5. **Pydantic** — veri doğrulama kütüphanesi
   - FastAPI içinde her yerde kullanılıyor; temel `class Model(BaseModel)` yapısı yeterli

---

## API Nedir? (Çok Temel)

API = Application Programming Interface = Uygulama Programlama Arayüzü

Bir restoranı düşün:
- **Menü** = API dokümantasyonu (ne isteyebilirsin)
- **Garson** = API (isteği alıp mutfağa iletir)
- **Mutfak** = Backend mantığı (asıl iş)
- **Yemek** = Cevap (sonuç)

Sen müşteri olarak menüden seçim yaparsın. Arka tarafta ne olduğunu bilmene gerek yok.

---

## HTTP vs WebSocket Farkı

Projede ikisi de var. Farkı anlamak önemli:

**HTTP (Klasik):**
```
Kullanıcı → "Merhaba, olay listesini ver"
Sunucu    → "Buyur, işte liste"
Bağlantı kapanır.
```
Her istekte bağlantı tekrar açılır, cevap gelir, kapanır. "Söyle-Cevapla" modeli.

**WebSocket (Sürekli Bağlantı):**
```
Kullanıcı → "Bağlandım, hazırım"
[Bağlantı açık kalır]
Kullanıcı → kare gönder
Sunucu    → sonuç gönder
Kullanıcı → kare gönder
Sunucu    → sonuç gönder
...
[Kullanıcı kapanana kadar devam eder]
```
Kapı açık tutulur, iki taraf istediği zaman mesaj atar.

Projemizde:
- **HTTP** → tek seferlik işler: giriş doğrulama, olay listesi, sistem durumu
- **WebSocket** → sürekli akan şeyler: kare gönderme, anlık sonuç alma

---

## Backend Dosya Yapısı

```
backend/
├── main.py              Ana dosya — tüm API uç noktaları burada
├── qod_manager.py       QoD yönetimi (tetik motoru + CAMARA köprüsü)
├── db.py                SQLite veritabanı işlemleri
├── frames.py            Kare çözümleme (base64/JPEG → numpy)
└── camara/
    ├── qod.py           Mock CAMARA QoD API simülasyonu
    └── number_verification.py  Mock CAMARA Number Verification
```

---

## `backend/main.py` — Tüm API Uç Noktaları

### Uygulama Başlangıcı

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = AppState()  # Pipeline, QoD, DB, CAMARA — hepsini başlat
    yield
    state.store.close()  # Kapanırken DB'yi kapat
```

`AppState` = sunucunun hafızası. Tüm bileşenler burada tutulur:

```python
class AppState:
    pipeline    # YZ işlem hattı
    qod         # QoD yöneticisi
    store       # SQLite veritabanı
    numverif    # CAMARA Number Verification
    subscribers # WebSocket bağlı dinleyiciler
```

---

### REST API Uç Noktaları

#### `GET /api/health` — Sistem Sağlık Kontrolü

```json
{
  "status": "ok",
  "ai_mode": "real",
  "detector": "YoloDetector",
  "qod_mode": "NORMAL",
  "version": "1.0.0"
}
```

Sistemi kontrol etmek için sürekli kullanılır. Curl ile test:
```bash
curl http://localhost:8000/api/health
```

---

#### `POST /camara/number-verification:verify` — Sessiz Giriş

CAMARA Number Verification API'sini simüle eder.
Gerçekte: Turkcell şebekesine "bu cihaz token'ı bu numarayı kullanıyor mu?" diye sorar.
Bizim mock'ta: Önceden tanımlı kayıtlara bakıp onaylar.

İstek:
```json
{
  "device_token": "device-guard-01",
  "phone_number": "+905320001122"
}
```

Cevap:
```json
{
  "devicePhoneNumberVerified": true,
  "token": "eyJ..."
}
```

Demo kayıtlar `backend/camara/number_verification.py`'de tanımlı.

---

#### `GET /api/events` — Olay Listesi

Riskli olayları listeler. Parametreler:
- `limit`: kaç olay (varsayılan 50)
- `min_score`: minimum risk skoru (varsayılan 0)

```bash
curl "http://localhost:8000/api/events?min_score=60&limit=10"
```

---

#### `GET /api/qod/status` — QoD Durumu

```json
{
  "mode": "NORMAL",
  "bandwidth_mbps": 5,
  "active_session_id": null,
  "last_trigger_reason": null,
  "session_age_s": 0,
  "bandwidth_efficiency": 0.82
}
```

`bandwidth_efficiency`: Bant genişliğini ne kadar verimli kullandık.
0.82 = zamanın %82'sinde düşük bantta kaldık = iyi performans.

---

#### `POST /api/clear` — Veritabanı Temizle

Test sırasında biriken sahte verileri siler.

```bash
curl -X POST http://localhost:8000/api/clear
```

---

### WebSocket Uç Noktaları

#### `WebSocket /ws/ingest` — Kare Alma Soketi

Bu projenin en önemli uç noktası. Ön yüz buraya bağlanıp kare yollar.

**Gelen mesaj formatı:**
```json
{
  "frame": "data:image/jpeg;base64,/9j/4AAQ..."
}
```

**Giden cevap formatı (FrameResult):**
```json
{
  "frame_id": 142,
  "mode": "NORMAL",
  "detections": [...],
  "vehicle": {
    "plate": {"text": "34ABC1234", "confidence": 0.85},
    "speed_kmh": 47.2,
    "vtype": "car"
  },
  "driver": {"phone_use": false, "fatigue": false},
  "risk": {"score": 0, "level": "LOW", "factors": []},
  "qod": {"mode": "NORMAL", "bandwidth_mbps": 5, ...},
  "fps": 6.2,
  "latency_ms": 87.3
}
```

**İçeride ne oluyor:**
```python
async def _process_frame(frame):
    # 1. YZ pipeline'a kareyi ver
    result, ctx = state.pipeline.process(frame, critical=state.qod.is_critical)
    # 2. QoD motorunu adımla
    qod_status = state.qod.step(ctx, dt_s=0.5)
    # 3. Sonuca QoD bilgisini ekle
    result.qod = qod_status
    # 4. Riskli olaysa veritabanına kaydet
    state.maybe_record(result)
    # 5. Dinleyen abonelere de yayınla
    await state.broadcast(payload)
    return payload
```

#### `WebSocket /ws/detections` — Salt Okunur Abone

Birden fazla ekran aynı anda sonuçları görmek isterse buraya bağlanır.
`/ws/ingest`'ten farkı: kare GÖNDERİLMEZ, sadece sonuçlar ALINIR.

---

## CAMARA API'leri (`backend/camara/`)

### CAMARA Nedir?

CAMARA = Cloud ARchitecture for Mobile Access — 5G şebeke API'lerini standartlaştıran
açık kaynak bir proje. Turkcell ve dünya genelinde büyük operatörler bu standardı
destekliyor.

Biz iki CAMARA API'si kullanıyoruz:

#### 1. Number Verification
"Bu cihaz, bu telefon numarasına sahip mi?" sorusunu SMS/kod gerektirmeden yanıtlar.
Kullanıcı hiçbir şey yapmadan arka planda SIM doğrulanır.

#### 2. Quality on Demand (QoD)
"Şu anda bu cihaza X Mbps bant genişliği garantisi ver" der.
Bant kaldırılacağında "oturumu sil" isteği gönderilir.

### Mock (Simülasyon) Neden Var?

Gerçek CAMARA API'sine erişmek için Turkcell operatör anlaşması gerekiyor.
Yarışma için gerçek API yoktu, bu yüzden tamamen aynı davranışta bir simülasyon yazdık.

Simülasyon dosyaları:
- `backend/camara/number_verification.py` — sabit kayıtlı SIM doğrulama
- `backend/camara/qod.py` — bant genişliği oturumu simülasyonu

Gerçek API geldiğinde bu iki dosyayı değiştirmen yeterli, geri kalan kod aynı kalır.

---

### `backend/camara/qod.py` — QoD Simülasyonu

```python
class MockQoDProvider:
    def create_session(device, qos_profile, duration_s, requested_mbps):
        # Oturum oluştur, ID döndür, bant 5→20 Mbps olarak işaretle

    def delete_session(session_id):
        # Oturumu sil, bant 20→5 Mbps geri dönsün

    def current_bandwidth_mbps():
        # Şu an aktif oturum varsa 20, yoksa 5 döndür
```

---

## `backend/qod_manager.py` — Tetik Motoru Köprüsü

YZ'nin `qod_trigger.py`'si saf mantık çalıştırır (ağ çağrısı yok).
`qod_manager.py` bu kararı CAMARA API'ye bağlar:

```
QoDTriggerEngine.evaluate(ctx) → "Kritik moda geç"
    ↓
MockQoDProvider.create_session() → "20 Mbps oturumu açıldı"
```

Bant verimliliği de burada ölçülür:
```python
bandwidth_efficiency = 1 - (kritik_döngü_sayısı / toplam_döngü_sayısı)
```
0.82 = zamanın %18'inde yüksek banttaydık = %82 tasarruf. İdeal.

---

## `backend/db.py` — Veritabanı

SQLite kullanıyoruz. SQLite = tek dosya içinde tam veritabanı. Kurulum gerektirmez.

### Tablo Yapısı (events):

```sql
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL,           -- Unix timestamp
    plate       TEXT,           -- Plaka metni (yoksa NULL)
    vtype       TEXT,           -- Araç tipi (car, truck...)
    speed_kmh   REAL,           -- Hız
    risk_score  INTEGER,        -- 0-100
    risk_level  TEXT,           -- LOW/MEDIUM/HIGH/CRITICAL
    factors     TEXT,           -- Virgülle ayrılmış faktörler
    mode        TEXT            -- NORMAL / CRITICAL
)
```

### Kayıt Mantığı:

Risk skoru ≥ 30 olan olaylar kaydedilir. Spam önleme için saniyede en fazla bir kayıt.

```python
def maybe_record(self, result):
    if result.risk.score >= 30 and (result.ts - self._last_event_ts) > 1.0:
        self.store.add(EventRecord(...))
```

---

## `backend/frames.py` — Kare Çözümleme

Ön yüzden gelen JPEG verisi → NumPy dizisi dönüşümü:

```python
def decode_data_url(data_url: str) -> np.ndarray:
    # "data:image/jpeg;base64,..." → base64 çöz → JPEG decode → NumPy array
```

---

## `config/settings.py` — Tüm Ayarlar

Tüm eşikler, model yolları ve parametreler buradan okunur. `.env` dosyasından
da geçersiz kılınabilir:

```env
AI_MODE=mock              # real / mock / auto
YOLO_MODEL_NORMAL=yolov8n.pt
CONF_NORMAL=0.35          # Tespit güven eşiği (normal mod)
QOD_EVAL_PERIOD_MS=500    # QoD değerlendirme aralığı
SPEED_CALIBRATION_K=900.0 # Hız kalibrasyon sabiti
```

Örnek dosya: `.env.example`

---

## Sunucu Nasıl Başlatılır?

```bash
# Geliştirme (otomatik yeniden başlama, kod değişince):
./run_dev.sh
# veya:
AI_MODE=auto .venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Mock modda (YZ modelleri olmadan):
AI_MODE=mock .venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API'yi Test Etmek

### Otomatik Testler

```bash
# Tüm backend testleri:
make test

# Spesifik dosyalar:
.venv/bin/python -m pytest tests/test_health.py -v
.venv/bin/python -m pytest tests/test_camara_qod.py -v
.venv/bin/python -m pytest tests/test_camara_numverif.py -v
.venv/bin/python -m pytest tests/test_events_api.py -v
.venv/bin/python -m pytest tests/test_ws_e2e.py -v
```

### Manuel Test (Curl ile)

```bash
# Sağlık kontrolü
curl http://localhost:8000/api/health

# SIM doğrulama
curl -X POST http://localhost:8000/camara/number-verification:verify \
  -H "Content-Type: application/json" \
  -d '{"device_token":"device-guard-01","phone_number":"+905320001122"}'

# Olay listesi (min_score=30 filtreli)
curl "http://localhost:8000/api/events?min_score=30&limit=20"

# QoD durumu
curl http://localhost:8000/api/qod/status

# Manuel QoD oturumu aç
curl -X POST http://localhost:8000/camara/qod/sessions \
  -H "Content-Type: application/json" \
  -d '{"device":"device-guard-01","qos_profile":"QOS_S_HIGH_THROUGHPUT"}'
```

### FastAPI Otomatik Dökümantasyon

Backend çalışırken tarayıcıda:
- `http://localhost:8000/docs` → Swagger UI (tıklanabilir API test arayüzü)
- `http://localhost:8000/redoc` → ReDoc formatı

Burada her uç noktayı tarayıcıdan deneyebilirsin, curl'a gerek yok.

---

## Yeni Bir API Uç Noktası Eklemek

Basit bir GET uç noktası örneği:

```python
@app.get("/api/statistics")
async def statistics():
    """Son 1 saatin olay istatistikleri"""
    events = state.store.list(limit=1000, min_score=0)
    return {
        "total": len(events),
        "high_risk": sum(1 for e in events if e.risk_score >= 60),
        "avg_speed": sum(e.speed_kmh or 0 for e in events) / max(len(events), 1),
    }
```

Bu kadar. FastAPI dekoratörü + async fonksiyon → çalışır.

---

## CORS Nedir? Neden Var?

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```

Tarayıcı güvenlik kuralı: "farklı adresten gelen istekleri engelle".
Örneğin, `localhost:3000`'daki mobil uygulama `localhost:8000`'e istek atarken
tarayıcı normalde bunu engeller. CORS middleware bu engeli kaldırır.

`allow_origins=["*"]` = herkese izin ver. Geliştirme ortamı için uygun,
production'da spesifik origin listesi verilmeli.

---

## Sık Karşılaşılan Sorunlar

**"Address already in use" hatası:**
```bash
# Port 8000'i kullanan işlemi bul ve kapat:
lsof -i :8000
kill -9 <PID>
```

**"Module not found" hatası:**
```bash
# Sanal ortamı aktif etmeyi unutmuş olabilirsin:
source .venv/bin/activate
# veya doğrudan:
.venv/bin/python -m uvicorn ...
```

**WebSocket bağlantısı hemen kopuyor:**
Genellikle backend'de exception oluşuyor. Terminal çıktısına bak — hata mesajı orada.

**Veritabanı kilitli hatası:**
Birden fazla sunucu örneği çalışıyor olabilir. Tüm Python işlemlerini kapat:
```bash
pkill -f "uvicorn backend.main"
```

---

## İyileştirme Fikirleri (Yapılabilecekler)

1. Gerçek CAMARA API entegrasyonu (Turkcell sandbox'u varsa)
2. `GET /api/statistics` uç noktası — toplam olay sayısı, ortalama hız vs.
3. `GET /api/vehicles/{plate}` — belirli plakaya ait tüm olaylar
4. Olay filtreleme: tarih aralığı, risk seviyesi, araç tipi
5. Rate limiting — tek IP'den saniyede çok fazla istek gelirse engelle
6. JWT tabanlı gerçek kimlik doğrulama (şu an mock token var)
7. PostgreSQL'e geçiş (ölçeklenebilirlik için SQLite yerine)

---

## Faydalı Kaynaklar

- [FastAPI Resmi Dökümantasyonu](https://fastapi.tiangolo.com/)
- [Pydantic v2 Dökümantasyonu](https://docs.pydantic.dev/)
- [WebSocket MDN Açıklaması](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API)
- [CAMARA Proje GitHub](https://github.com/camaraproject)
- [SQLite Tutorial](https://www.sqlitetutorial.net/)
- Proje içi testler: `tests/test_health.py`, `tests/test_ws_e2e.py`
