# Entegrasyon Kolu Rehberi — Sistem Bütünleştirme, Web Arayüzü & Test

> Bu belge entegrasyon kolunda çalışanlar için yazıldı. YZ, API ve Mobil kollarının
> ürettiklerini bir araya getirip çalışır hale getirmek, web arayüzünü yönetmek
> ve tüm sistemi test etmek bu kolun işi.

---

## Sen Ne Yapacaksın?

Entegrasyon kolu "yapıştırıcı" görevi görür. Her kol kendi işini yapar ama
hepsinin birlikte çalışması için birisinin köprü kurması gerekir.

Somut görevlerin:
- Web arayüzünü (`frontend/`) geliştirmek ve güncel tutmak
- Sistemin tümünü ayağa kaldırıp uçtan uca test etmek
- YZ çıktısının API'ye, API çıktısının ön yüze doğru gittiğini doğrulamak
- Testleri yazmak ve geçmesini sağlamak
- Herhangi bir kol yeni şey eklediğinde uyumu test etmek
- Sorunları tespit edip ilgili kola bildirmek

---

## Önce Bunları Öğren

1. **HTML/CSS temelleri** — web sayfası nasıl yapılır
   - Kaynak: MDN Web Docs — "HTML basics" ve "CSS basics"

2. **JavaScript temelleri** — async/await, fetch, WebSocket
   - Kaynak: javascript.info

3. **pytest** — Python ile test yazma
   - Kaynak: pytest'in resmi "Getting Started" sayfası (10 dakika)

4. **HTTP curl ile test etmek** — komut satırından API'ye istek atmak
   - Birkaç curl örneği denemen yeterli (bu belgede var)

5. **Git temelleri** — branch, merge, pull request
   - Kaynak: git-scm.com/doc veya "Git for Beginners" YouTube

---

## Entegrasyon Ne Demek?

Farklı ekiplerin yazdığı parçaların birlikte çalışmasını sağlamak.

Örnek senaryo:
- YZ kolu yeni bir alan ekledi: `FrameResult`'a `vehicle.color` eklendi
- API kolu bunu backend'den iletmeli
- Web arayüzü bunu ekranda göstermeli
- Mobil uygulama da bunu okumalı

Bu değişikliğin tüm parçalarda tutarlı uygulandığını test etmek entegrasyon işi.

---

## Web Arayüzü (`frontend/`)

### Dosyalar

```
frontend/
├── index.html    Sayfa iskelet yapısı (HTML elementleri)
├── app.js        Tüm JavaScript mantığı (kamera, WebSocket, çizim)
└── styles.css    Görsel tasarım
```

Web arayüzü **backend tarafından sunuluyor**. Tarayıcıda `http://localhost:8000/`
yazınca backend bu HTML dosyasını gönderiyor. Ayrı bir web sunucusu gerekmiyor.

Bu şu anlama geliyor: Frontend geliştirirken `./run_dev.sh` çalışıyor olmalı.
Dosyayı kaydettin mi? Sayfayı yenile (F5) — değişiklikler görünür.

---

### `frontend/app.js` — Kamera & WebSocket Akışı

Web uygulaması kamerayı `getUserMedia` API'siyle açar:

```javascript
stream = await navigator.mediaDevices.getUserMedia({
  video: { facingMode: "environment" },  // Arka kamera (varsa)
  audio: false
});
video.srcObject = stream;  // Video elementine bağla
```

Kare gönderme döngüsü saniyede 7 kez çalışır:

```javascript
function pump() {
  if (!sending) return;

  // Video karesini canvas'a çiz, 640px'e küçült
  captureCanvas.width = 640;
  captureCanvas.height = Math.round(640 * video.videoHeight / video.videoWidth);
  ctx.drawImage(video, 0, 0, 640, captureCanvas.height);

  // Canvas içeriğini JPEG base64 olarak WebSocket'e gönder
  ws.send(JSON.stringify({
    frame: captureCanvas.toDataURL("image/jpeg", 0.6)  // %60 kalite
  }));

  setTimeout(() => requestAnimationFrame(pump), 1000 / 7);  // 7 FPS
}
```

Gelen sonuçlar ekrana çizilir:

```javascript
ws.onmessage = ev => {
  const data = JSON.parse(ev.data);
  render(data);   // panelleri güncelle
  drawOverlay(data);  // kamera üzerine kutu çiz
};
```

---

### `drawOverlay` — Tespit Kutularını Çizmek

Backend koordinatları 640px genişliğine göre — ekran farklı boyutta.
Ölçek hesabı:

```javascript
const sx = overlay.width / 640;  // ekran/gönderilen boyut oranı

detections.forEach(det => {
  const x = det.bbox.x1 * sx;
  const y = det.bbox.y1 * sx;
  const w = (det.bbox.x2 - det.bbox.x1) * sx;
  const h = (det.bbox.y2 - det.bbox.y1) * sx;

  ctx.strokeStyle = det.label === "vehicle" ? "#2f7bff"
                  : det.label === "phone" ? "#ff4d5e"
                  : "#2ecc71";
  ctx.strokeRect(x, y, w, h);
  ctx.fillText(`${det.label} ${(det.confidence * 100)|0}%`, x, y - 4);
});
```

---

### Kamera Listesi (Birden Fazla Kamera)

```javascript
async function listCameras() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const cameras = devices.filter(d => d.kind === "videoinput");
  // Dropdown'a ekle
  cameras.forEach((cam, i) => {
    const option = document.createElement("option");
    option.value = cam.deviceId;
    option.textContent = cam.label || `Kamera ${i + 1}`;
    cameraSelect.appendChild(option);
  });
}
```

Mac'te dahili kamera + iPhone (Continuity Camera) görünebilir.
Android/iOS Chrome'da arka/ön kamera seçilebilir.

---

### SIM Doğrulama Akışı (Web)

```javascript
loginBtn.onclick = async () => {
  const response = await fetch("/camara/number-verification:verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_token, phone_number })
  });
  const data = await response.json();

  if (data.devicePhoneNumberVerified) {
    loginMask.style.display = "none";  // Giriş ekranını gizle
    sessionStorage.setItem("authToken", data.token || "");
  }
};
```

---

## Test Altyapısı (`tests/`)

### Dosyalar

```
tests/
├── conftest.py               Ortak test yapılandırması (mock fixtures)
├── test_health.py            /api/health uç noktası testi
├── test_camara_qod.py        CAMARA QoD API testi
├── test_camara_numverif.py   Number Verification testi
├── test_events_api.py        Olay listesi API testi
├── test_pipeline_schema.py   YZ pipeline veri tipleri testi
├── test_qod_trigger.py       QoD tetik motoru mantık testi
├── test_risk.py              Risk skoru hesaplama testi
├── test_speed.py             Hız tahmini testi
└── test_ws_e2e.py            WebSocket uçtan uca testi
```

---

### Testleri Çalıştırmak

```bash
# Tüm testler:
make test
# Bu aslında şunu çalıştırır:
AI_MODE=mock .venv/bin/python -m pytest

# Sadece bir test dosyası:
.venv/bin/python -m pytest tests/test_health.py -v

# Sadece bir test fonksiyonu:
.venv/bin/python -m pytest tests/test_risk.py::test_phone_use -v

# Hata çıktısını görmek için:
.venv/bin/python -m pytest -v --tb=short
```

`-v` = verbose = daha fazla çıktı göster

---

### `conftest.py` — Test Hazırlığı

```python
@pytest.fixture
def client():
    """Test için FastAPI istemcisi (gerçek sunucu başlatmaz)"""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        yield c
```

`TestClient` = gerçek HTTP sunucu başlatmadan API'yi test eder.
Çok hızlı ve güvenilir.

---

### Test Örneği Okuma

```python
def test_health(client):
    """Sağlık uç noktasının doğru cevap verdiğini kontrol et"""
    response = client.get("/api/health")          # HTTP GET isteği
    assert response.status_code == 200             # 200 = başarılı
    data = response.json()
    assert data["status"] == "ok"                  # "ok" gelmeli
    assert "ai_mode" in data                       # ai_mode alanı olmalı
```

`assert` = "bu doğru olmalı, değilse test başarısız" demek.

---

### Yeni Test Yazmak

Örnek: `/api/qod/status` uç noktasını test et

```python
def test_qod_status_format(client):
    """QoD durum cevabının beklenen alanları içerdiğini doğrula"""
    response = client.get("/api/qod/status")
    assert response.status_code == 200
    data = response.json()

    # Bu alanlar olmalı:
    assert "mode" in data
    assert "bandwidth_mbps" in data
    assert "bandwidth_efficiency" in data

    # Mode değerleri sadece bunlar olabilir:
    assert data["mode"] in ["NORMAL", "CRITICAL"]

    # Bant genişliği pozitif olmalı:
    assert data["bandwidth_mbps"] > 0
```

---

### WebSocket Testi (`test_ws_e2e.py`)

```python
def test_ws_frame_receives_result(client):
    """Kare gönderince FrameResult cevabı gelmeli"""
    # Küçük siyah JPEG kare oluştur (mock için yeterli)
    img = Image.new("RGB", (64, 64), color=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    with client.websocket_connect("/ws/ingest") as ws:
        ws.send_json({"frame": f"data:image/jpeg;base64,{b64}"})
        result = ws.receive_json()

        assert "mode" in result        # NORMAL veya CRITICAL
        assert "detections" in result  # tespit listesi
        assert "risk" in result        # risk skoru
```

---

## Uçtan Uca Senaryo Testi (Manuel)

Tüm sistemi birlikte test etmek için:

### Adım 1: Backend'i başlat

```bash
./run_dev.sh
```

Çıktıda `Application startup complete` görünce hazır.

### Adım 2: Sağlık kontrolü

```bash
curl http://localhost:8000/api/health
# Beklenen: {"status":"ok","ai_mode":"real",...}
```

### Adım 3: SIM doğrulama

```bash
curl -X POST http://localhost:8000/camara/number-verification:verify \
  -H "Content-Type: application/json" \
  -d '{"device_token":"device-guard-01","phone_number":"+905320001122"}'
# Beklenen: {"devicePhoneNumberVerified":true,"token":"..."}
```

### Adım 4: Tarayıcıda test

`http://localhost:8000/` aç → Login → Kamerayı Başlat → Sonuçları izle.

### Adım 5: WebSocket manuel test

Tarayıcı konsolunu aç (F12) ve yapıştır:

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/ingest");
ws.onmessage = e => console.log(JSON.parse(e.data));
```

Bir sonraki mesaj geldiğinde konsolda göreceksin.

### Adım 6: Olay kaydını kontrol et

Kamera biraz çalıştıktan sonra:
```bash
curl "http://localhost:8000/api/events?min_score=0&limit=5"
```

---

## Mock Video Oluşturma

Kamera olmadan sistem testleri için sentetik video:

```bash
make mock
# Sonuç: mock/sample_frames/ klasörü ve mock/video.mp4
```

Bu video basit geometrik şekillerden oluşuyor — gerçek araç değil.
Ama sistemin uçtan uca çalıştığını kanıtlar.

---

## Doğruluk Değerlendirmesi

```bash
make eval
```

Bu komut:
1. `mock/make_mock_video.py` ile sentetik kareler üretir
2. `eval/evaluate.py` ile Normal ve Kritik profilleri karşılaştırır
3. Konsola doğruluk raporu basar

Raporda şunları görürsün:
- Araç tespiti yüzdesi (kaç karede araç bulundu)
- QoD tetiklenme oranı (kaç kerede Kritik moda geçildi)
- Ortalama güven skoru
- Normal vs Kritik profil karşılaştırması

---

## Kollar Arası İletişim: Veri Kontratı

Kolların birbirine ne gönderdiğini anlamak entegrasyonun temelidir.

### YZ → API (TriggerContext)

```python
class TriggerContext:
    bbox_growth: float           # Araç bbox'ının büyüme oranı
    vehicle_present: bool        # Araç görünüyor mu?
    vehicle_conf: float          # Araç güveni (0-1)
    vehicle_norm_y2: float       # Araç alt kenarı (normalize, 0-1)
    plate_roi_present: bool      # Plaka bölgesi var mı?
    plate_ocr_conf: float        # OCR güveni
    ambiguous_object_confs: list # Sınır güvendeki nesneler
```

### YZ → API (FrameResult)

```python
class FrameResult:
    frame_id: int
    mode: str                    # "NORMAL" | "CRITICAL"
    detections: List[Detection]  # Tüm tespitler
    vehicle: Vehicle             # Ana araç bilgisi
    driver: DriverState          # Sürücü durumu
    risk: RiskAssessment         # Risk skoru
    qod: QoDStatus               # QoD bilgisi
    fps: float
    latency_ms: float
```

### API → Frontend (JSON over WebSocket)

`FrameResult.model_dump()` çıktısı — aynı yapı, JSON olarak.

---

## Sık Karşılaşılan Sorunlar

**"Testler geçiyor ama tarayıcıda çalışmıyor":**
- Testler mock modda çalışır, tarayıcı gerçek model kullanır
- AI_MODE=real ile sunucuyu başlatıp tarayıcıda dene

**"CORS hatası" tarayıcı konsolunda:**
- Backend `allow_origins=["*"]` ayarlı olmalı (zaten var)
- Sayfayı `localhost:8000`'den değil başka yerden açmaya çalışıyorsun olabilir

**"WebSocket bağlantısı hemen kopuyor":**
- Backend terminali hata logunu incelemek için en iyi kaynak
- Genellikle kare decode edilemiyor (bozuk base64) veya backend exception

**"Kamera açılmıyor tarayıcıda":**
- Chrome: `localhost`'ta kamera izni otomatik verilir, IP üzerinden değil
- IP üzerinden test için HTTPS gerekir VEYA Chrome'da `chrome://flags/#unsafely-treat-insecure-origin-as-secure` ayarı

**Testler `import` hatası veriyor:**
- `.venv/bin/python -m pytest` kullandığından emin ol (sadece `pytest` değil)
- Ya da `source .venv/bin/activate` sonra `pytest`

---

## Entegrasyon Kontrol Listesi (Her PR Öncesi)

Yeni bir değişiklik geldiğinde bunları kontrol et:

- [ ] `make test` çalıştı ve tüm testler yeşil
- [ ] `curl http://localhost:8000/api/health` → `{"status":"ok"}`
- [ ] Tarayıcıda kamera açılıyor ve sonuçlar geliyor
- [ ] WebSocket bağlantısı kopmuyor (30 saniye izle)
- [ ] `/api/events` sorgusunda veri geliyor (kamera biraz çalıştıktan sonra)
- [ ] Yeni eklenen alan varsa web arayüzünde ve mobilde görünüyor
- [ ] Hız, plaka ve risk skorları `—` veya gerçekçi değerler (3 km/h gibi şüpheli rakamlar yok)

---

## Neler Geliştirilebilir?

1. **CI/CD** — GitHub Actions ile her push'ta testler otomatik koşsun
2. **Playwright** — tarayıcıda otomatik uçtan uca test (kamera simüle edilebilir)
3. **Stres testi** — saniyede kaç kare gönderince backend yavaşlar?
4. **Performans monitörü** — `latency_ms` değerlerini ekranda grafik olarak izle
5. **Hata izleme** — frontend JS hatalarını backend'e loglayacak mekanizma
6. **Docker** — tüm sistemi tek komutla başlatan container

---

## Faydalı Kaynaklar

- [pytest Dökümantasyonu](https://docs.pytest.org/en/stable/)
- [FastAPI TestClient](https://fastapi.tiangolo.com/tutorial/testing/)
- [MDN WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
- [Chrome DevTools (F12) Kullanımı](https://developer.chrome.com/docs/devtools/)
- [getUserMedia Kamera API](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- Proje testleri: `tests/test_ws_e2e.py` (en iyi örnek)
