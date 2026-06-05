# Sonraki Adımlar (next.md)

**Oluşturulma:** 2026-06-05  
**Durum:** Kol sorumluları tarafından paylaşılacak görevler

---

## 🔴 Kritik (Demo Öncesi Mutlaka)

### 1. Sigara / Sigara İçme Tespiti
**Sorun:** COCO ön-eğitimli YOLOv8'de `cigarette` sınıfı yoktur. video_2.mp4'te sürücünün sigara içtiği görülüyor ancak tespit edilemiyor.

**Çözüm seçenekleri (kolaydan zora):**
1. HuggingFace'den sigara tespiti yapan hazır YOLOv8 modeli indirin (ör. Roboflow'un açık modelleri).
2. `ai/detector.py` içindeki `COCO_TO_CANONICAL` map'ine `"cigarette"` ekleyin ve `yolo_model_critical` olarak fine-tuned model kullanın.
3. Alternatif: el-yüz mesafesi + küçük ateş rengi bölgesi heuristic (MediaPipe el tespiti ile).

**Dosyalar:** `ai/detector.py`, `config/settings.py`, `ai/driver_state.py`, `ai/risk.py`

---

### 2. Plaka OCR — video_3 Karanlık Sahne
**Sorun:** video_3.mp4 yeraltı otopark — ham parlaklık ort. ~29. CLAHE + gamma düzeltmesi eklendi ama EasyOCR hâlâ düşük güvenle okuyor ("J4UC8532" → "34UC8532" düzeltmesiyle geçiyor, asıl plaka "34TC8532").

**Çözüm seçenekleri:**
1. **YOLOv8 plaka dedektörü:** `keremberke/yolov8n-license-plate-detection` modeli 401 hatası veriyor (gated). Alternatif açık model bulun veya Roboflow API ile test edin.
2. **PaddleOCR:** EasyOCR yerine PaddleOCR kurulumu → karanlık sahnelerde daha başarılı.
3. **Çerçeve birikimi:** Pipeline zaten 8-kare konsensüs yapıyor; video test için 30-60 kare biriktirip en sık görülen plakayı seçin.
4. **YOLOv8x modeli:** Proje dizininde `yolov8x.pt` (henüz tam değil, 1.9MB — tamamlayın). Kritik profilde yolov8x kullanılırsa araç tespiti iyileşir → plaka kırpması daha doğru.

**Dosyalar:** `ai/lp_detector.py`, `ai/plate_ocr.py`

---

### 3. YOLOv8x Model Tamamlama
**Sorun:** `yolov8x.pt` dosyası 1.9MB (bozuk/eksik). Kritik profil için `yolov8x` (130MB) kullanılması gerekiyor.

```bash
# Manuel indirme
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8x.pt
# veya
python -c "from ultralytics import YOLO; YOLO('yolov8x.pt')"
```

**Dosyalar:** `config/settings.py` → `yolo_model_critical = "yolov8x.pt"` (hazır, sadece model eksik)

---

## 🟡 Önemli (Sprint İçinde)

### 4. Emniyet Kemeri Tespiti
**Sorun:** COCO'da `seatbelt` sınıfı yok. Şu an `no_seatbelt = False` hard-coded.

**Çözüm:** YOLOv8 seatbelt detection modeli (Roboflow açık dataset mevcuttur) veya renk-bölge heuristic (göğüs bölgesinde koyu şerit tespiti).

---

### 5. Android Mobil Uygulama
**Sorun:** `mobile/` klasörü var ama eksik implementasyon.

**Gereksinimler:**
- WebSocket bağlantısı (`ws://BACKEND_IP:8000/ws/stream`)
- Kamera akışı gönderimi (JPEG base64 veya binary)
- Overlay UI: araç kutuları, plaka, hız, uyarılar

**Dosyalar:** `mobile/` klasörü, `docs/mobil.md`

---

### 6. Hız Tahmini Kalibrasyonu
**Sorun:** Kamera focal length ve araç gerçek boyutu bilinmeden piksel-tabanlı hız tahmini yalnızca görecelidir.

**Çözüm:** `config/settings.py` içine `CAMERA_FOCAL_PX`, `VEHICLE_LENGTH_M` sabitlerini ekleyin. `ai/speed.py` zaten bu yapıyı destekliyor ama değerler varsayılan.

---

### 7. 5G QoD API — Gerçek Bağlantı
**Sorun:** `ai/qod_trigger.py` ve `backend/camara_api.py` mock implementasyon.

**Gereksinim:** CAMARA QoD API gerçek credentials ile test ortamına bağlanacak. API kolunun tamamlaması gerekiyor.

**Dosyalar:** `backend/camara_api.py`, `docs/api.md`

---

## 🟢 İyileştirme (Vakit Olursa)

### 8. Frontend — Gerçek Zamanlı Grafik
- Hız grafiği (son 30 kare)
- Risk skoru zaman çizelgesi
- Plaka okuma güven göstergesi

### 9. Test Coverage
- `tests/test_plate_ocr.py` — farklı ışık koşullarında OCR testi
- `tests/test_lp_detector.py` — CLAHE dedektör unit testi
- video_1 ve video_2 için end-to-end beklenen çıktılar

### 10. Docker / Deployment
- `Dockerfile` güncellenmeli (EasyOCR model dosyaları `COPY` ile)
- CI/CD: GitHub Actions YML dosyası

---

## Kol Sorumlusu Özeti

| Görev | Kol | Öncelik |
|-------|-----|---------|
| Sigara tespiti modeli | YZ | 🔴 Kritik |
| YOLOv8x model indirme | YZ | 🔴 Kritik |
| PaddleOCR veya OCR iyileştirme | YZ | 🔴 Kritik |
| Emniyet kemeri modeli | YZ | 🟡 Önemli |
| Android uygulama | Mobil | 🟡 Önemli |
| QoD API gerçek bağlantı | API | 🟡 Önemli |
| Hız kalibrasyonu | YZ + Entegrasyon | 🟡 Önemli |
| Frontend grafikler | Entegrasyon | 🟢 İyileştirme |
