# Changelog

Bu proje için tüm önemli değişiklikler bu dosyada belgelenir.
Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) esaslıdır.
Sürüm etiketleri şu an yalnız mobil uygulama içindir (`v1.0.0-mobile`, `v2.0.0-mobile`);
backend/YZ hattı sürümleri commit geçmişinden türetilmiştir.

> Not: Bu depo **v1 prototipidir**. Geliştirme
> [`teknofest-prototip.v2`](https://github.com/cleoanka/teknofest-prototip.v2)
> deposunda sürmektedir.

## [Yayınlanmamış]

### Eklendi
- MIT `LICENSE` dosyası (rozet ile uyum).
- Sürekli entegrasyon: `.github/workflows/ci.yml` (Python 3.10–3.12'de mock-mod pytest + ruff).
- `.editorconfig`, `[tool.ruff]` içeren `pyproject.toml`, bu `CHANGELOG.md`.
- `docs/history/` arşivi: kök dizinden taşınan planlama/ilerleme belgeleri.

### Düzeltildi
- README/ARCHITECTURE'daki bayat test sayıları (308/248 → **358**) ve test dosyası
  sayısı (27 → **33**) gerçek değerlere güncellendi; canlı CI rozeti eklendi.
- `backend/qod_manager.py` içindeki kullanılmayan `sess` ataması temizlendi.

## [v4 model] — 2026-06-08
### Değiştirildi
- Varsayılan CRITICAL model tip-ayrımlı **v4** (`yolguvenligi_types_v4.pt`,
  yolov8m@768, dondurulmuş omurga, held-out test mAP50 **0.788**) — v2 ağırlığı yerine.
- `.env.example` CRITICAL modeli `yolov8s.pt` → `models/yolguvenligi_types_v4.pt`.

## [Backend v1.5] — 2026-06-06
### Eklendi
- Zengin API v1.5: `system/info`, `qod/{sid}`, plaka dışa aktarım, statistics,
  vehicles/{plate}, events/{id}, heatmap, timeline, proof. (248 test)
- API v1.4: WebSocket token auth, `health/deep`, JSON loglama, Swagger,
  `X-Response-Time`; events sort + vehicles pagination + `/api/version`. (198 test)
- Prometheus `/metrics` + Grafana entegrasyonu; JWT RS256 kimlik doğrulama;
  100 req/dak rate limiting.
- Git LFS ile tip-ayrımlı model ağırlığı.

## [Mobil v2] — 2026-06-06 (`v2.0.0-mobile`)
### Değiştirildi
- Mobil uygulama sıfırdan yeniden yazıldı; Expo SDK 54 yükseltmesi + 6 yeni özellik.

## [İlk sürüm] — 2026-06-05 (`v1.0.0-mobile`)
### Eklendi
- İlk prototip: uçtan uca YZ hattı (detector, tracking, speed, plate_ocr,
  driver_state, risk, qod_trigger, pipeline), FastAPI backend, CAMARA QoD mock,
  web güvenlik konsolu, React Native / Expo mobil uygulama, 6 kol rehber belgesi.

<!-- Sonraki geliştirmeler (2026-06-07): metrik hız oto-kalibrasyonu (ppm/homografi/VP/PnP),
     ByteTrack+Kalman hız, plaka tespiti/crop/takip iyileştirmeleri, sürücü kimlik kilidi,
     telefon/sigara MediaPipe tespiti — commit geçmişinde ayrıntılı. -->
