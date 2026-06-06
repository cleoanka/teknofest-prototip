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

#### ⚠️ Kod incelemesi bulguları — commit `7dad35d` (fix(ai): plate_ocr & pipeline)

Bu committe çözülmesi gereken 3 sorun tespit edildi. OCR/plaka iyileştirmesiyle **birlikte** ele alınmalı:

1. **🔴 KRİTİK — Tüm process'te TLS doğrulaması kapalı.**
   `ai/plate_ocr.py:27` modül seviyesinde (girintisiz):
   ```python
   ssl._create_default_https_context = ssl._create_unverified_context
   ```
   `backend/main.py → ai.pipeline → ai.plate_ocr` import zinciri yüzünden backend ayağa kalktığı an
   **tüm sürecin** giden HTTPS sertifika doğrulaması kapanıyor (sadece EasyOCR indirme değil; webhook,
   dış API, JWT anahtarı vb. hepsi). MITM açığı — "yol güvenliği" temalı, jüriye sunulan projede kötü görünür.
   **Yapılacak:** Geniş yamayı kaldır; EasyOCR model indirmesini `certifi` CA paketiyle çöz ya da yamayı
   sadece ilk indirme çağrısının etrafına sarıp hemen geri al. İdeali: modeli önceden indirip imaja gömmek
   (bkz. Görev 10 — Docker `COPY`), böylece çalışma anında hiç HTTPS gerekmesin.

2. **🟠 Correctness — Yanlış araca plaka atanabilir.**
   `ai/pipeline.py` içinde `_nearest_plate_to_vehicle` "bu plaka başka araca ait" deyip `None` döndürdüğünde,
   çağıran taraf bunu ezip `max(plate_bboxes, key=area)` ile en büyük plakayı yine de atıyor → eşleştirme
   güvenlik kontrolü pratikte ölü kod. Çok araçlı sahnede bir araca başka aracın plakası atanabilir; plaka
   kanıt/QoD olarak kaydedildiği için yanlış kayıt riski.
   **Yapılacak:** Tek-araç (TOGG) senaryosu ile çok-araç senaryosunu ayır: çerçevede tek araç varsa fallback
   en büyük plaka kabul edilebilir; ≥2 araç varsa guard `None` döndürdüğünde plaka **atanmamalı**.

3. **🟠 OCR kabul eşiği 0.55 → 0.45'e düşürüldü** (`ai/plate_ocr.py`, `final_conf < 0.45`).
   Daha çok yanlış-pozitif okuma; #2 ile birleşince yanlış plaka kaydı artar. PaddleOCR/dedektör iyileştirmesi
   yapıldıktan sonra eşik tekrar ölçülerek ayarlanmalı (video_1/2/3 üzerinde precision/recall ile doğrula).

> Not: Commit mesajı plate_ocr.py için birçok iyileştirme (GPU/MPS, allowlist, CLAHE+Otsu 4-varyant, konsensüs)
> sayıyor ama gerçek diff'te yalnızca SSL satırı + eşik değişikliği var; geri kalan ya zaten dosyadaydı ya da
> bu committe değil. Ayrıca pipeline.py "committed versiyona restore" ile Canny tabanlı `_find_plate_crop`
> yaklaşımını geri alıyor — birinin bilerek eklediği bir şeyse sessizce reverter, kontrol edilmeli.

**Ek dosyalar:** `backend/main.py` (import zinciri), `Dockerfile` (model gömme)

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
| SSL global kapatma düzeltmesi (commit 7dad35d) | YZ + Güvenlik | 🔴 Kritik |
| Plaka-araç eşleştirme guard'ı (çok-araç) | YZ | 🔴 Kritik |
| Sigara tespiti modeli | YZ | 🔴 Kritik |
| YOLOv8x model indirme | YZ | 🔴 Kritik |
| PaddleOCR veya OCR iyileştirme | YZ | 🔴 Kritik |
| Emniyet kemeri modeli | YZ | 🟡 Önemli |
| Android uygulama | Mobil | 🟡 Önemli |
| QoD API gerçek bağlantı | API | 🟡 Önemli |
| Hız kalibrasyonu | YZ + Entegrasyon | 🟡 Önemli |
| Frontend grafikler | Entegrasyon | 🟢 İyileştirme |
