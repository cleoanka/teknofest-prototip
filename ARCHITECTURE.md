# Sistem Mimarisi — Akıllı Yol Güvenliği (5G & YZ)

## 1. Genel mimari ve veri akışı

```
┌────────────────────────┐      ┌──────────────────────────┐      ┌───────────────────────────┐
│  ÖN YÜZ                 │      │  BACKEND (FastAPI)        │      │  YZ ÇIKARIM HATTI (ai/)   │
│  • Mobil App (Expo)     │ WS   │  • /ws/ingest (kare giriş)│ call │  • detector  (YOLOv8)     │
│  • Web Dashboard        │─────▶│  • /ws/detections (yayın) │─────▶│  • tracking  (track_id)   │
│    (getUserMedia)       │ JSON │  • REST /api/*            │      │  • plate_ocr (kritik)     │
│  Kamera = yol kenarı    │◀─────│  • mock CAMARA /camara/*  │◀─────│  • driver_state (EAR)     │
│  kamera simülasyonu     │<3KB  │  • SQLite olay deposu     │      │  • speed / risk           │
└────────────────────────┘      └─────────────┬────────────┘      └───────────────────────────┘
        ▲                                      │ TriggerContext
        │ Number Verification (sessiz)         ▼
        │                          ┌──────────────────────────┐
        └──────────────────────────│  QoD MANAGER             │
                                   │  • QoDTriggerEngine (A–E)│
                                   │  • Mock CAMARA QoD        │  Normal 5Mbps ↔ Kritik 20Mbps
                                   └──────────────────────────┘
```

**Akış:** Ön yüz kamera karesini WS `/ws/ingest`'e yollar → backend kareyi hatta
verir → hat `FrameResult` + `TriggerContext` üretir → QoD Manager tetik koşullarını
değerlendirir, gerekiyorsa CAMARA QoD oturumu açar/kapatır ve modu (Normal/Kritik)
belirler → sonuç ingest soketine yanıt ve `/ws/detections` abonelerine yayın olarak
döner (<3 KB JSON) → riskli olay SQLite'a yazılır.

**Darboğaz önleme:** Normal modda hafif model + düşük çözünürlük; ağır işlemler
(OCR, yorgunluk) yalnız kritik modda. WS tek yönlü küçük JSON; video ayrı kanaldan.

## 2. YZ modeli ve çıkarım tasarımı

| Görev | Model/Yöntem | Profil | Veri (fine-tune) | Hedef metrik |
|---|---|---|---|---|
| Araç tespiti | YOLOv8n (INT8) | Normal | COCO+BDD100K | mAP@.5 ≥ 0.72 |
| Araç + nesne | YOLOv8s (INT8) | Kritik | COCO+BDD100K+TOGG | mAP@.5 ≥ 0.78 |
| Plaka OCR | EasyOCR/Paddle + çok-varyant + konsensüs | Kritik | TR plaka setleri | karakter ≥ 0.90 |
| Telefon/sigara | YOLOv8 kabin ROI | Kritik | COCO + özel | precision ≥ 0.80 |
| Yorgunluk | MediaPipe FaceMesh → EAR/PERCLOS | Kritik | DROZY | EAR<0.21 & PERCLOS>%40 |
| Hız | bbox_alan^0.65 + max(Δmerkez,Δalan) | her ikisi | kalibrasyonsuz | MAE ≤ 8 km/h |

**Doğruluk/gecikme dengesi:** profil ayrımı (n↔s), INT8 export (~%20-35 hız, <1.5
mAP kaybı), OCR ayrı thread, ROI crop. Mac'te MPS, NVIDIA'da TensorRT.

## 3. Akıllı QoD tetik algoritması (özgün katkı — %40 kriter)

500 ms döngüde 5 koşul; **iki ardışık pozitif**te QoD talep edilir:

```
A: bbox alan büyümesi > eşik          (araç yaklaşıyor)
B: araç tespit güveni < 0.55          (hafif model belirsiz)
C: plaka ROI var, OCR güveni < 0.75   (okuma için yüksek çözünürlük gerek)
D: araç ROI çizgisini geçti           (okuma menzili)
E: araç içi nesne sınır olasılıkta    (0.40–0.60)

(A|B|C|D|E) ve 2 ardışık → CAMARA QoD POST /sessions (20 Mbps, 5s)
Bırakma: güven>0.85  veya  süre doldu  veya  araç ROI dışında → DELETE /sessions/{id}
```
Bu, "sürekli açık musluk" yerine **ihtiyaç-bazlı** bant yönetimidir; `bandwidth_efficiency`
metriği sürekli-yükseğe göre tasarrufu ölçer.

## 4. Yazılım mimarisi

| Katman | Teknoloji | Görev |
|---|---|---|
| Mobil | React Native + Expo SDK 51 (TS) | Kamera, NumVerif girişi, canlı sonuç |
| Web | Vanilla JS + getUserMedia | Güvenlik konsolu, overlay, olay listesi |
| Backend | FastAPI 0.115 + Uvicorn | REST + WebSocket + QoD yönetimi |
| YZ | Ultralytics YOLOv8 + EasyOCR + MediaPipe | Çıkarım hattı |
| 5G API (mock) | CAMARA QoD + Number Verification sözleşmesi | Bant + sessiz doğrulama |
| Veri | SQLite (→ PostgreSQL'e taşınabilir) | Olay kaydı |

**Modern pratikler:** katmanlı/ayrık modüller, Pydantic tip-güvenli şema, saf-mantık
tetik motoru (kolay test), `async` WebSocket, graceful degradation (mock fallback),
38 testlik pytest paketi, tek-noktadan yapılandırma.

## 5. Mocktan gerçeğe geçiş yol haritası
- **Model:** `ai/training/train.py` ile TOGG/etiketli veride fine-tune → `best.pt`.
- **5G:** mock CAMARA → Turkcell gerçek uç noktası (yalnız base_url + auth değişir,
  çağrı sözleşmesi aynı).
- **Veri tabanı:** SQLite → PostgreSQL (şema aynı).
- **Medya:** getUserMedia → final'de Turkcell'in sağlayacağı canlı kamera API'si.
```
