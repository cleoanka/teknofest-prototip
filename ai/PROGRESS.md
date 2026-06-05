# PROGRESS.md — YZ Kolu İlerleme Günlüğü

> Kapsam: **Yapay Zeka kolu (`ai/`)**. Her teknik adımdan sonra buraya satır eklenir
> (ne yapıldı / neden / ölçülen sonuç). Kurallar için bkz. `AGENTS.md`.

## Proje
TEKNOFEST 2026 · 5G & YZ ile Akıllı Yol Güvenliği. Temel repo: `cleoanka/teknofest-prototip`.

---

## 1. Mevcut Durum (2026-06-05)

**Genel:**
- Prototip repo **temel alındı** ve çalışma klasörüne byte-perfect kuruldu (64 dosya, GitHub ile birebir).
- YZ hattı **uçtan uca çalışıyor** (mock + COCO ön-eğitimli YOLOv8 ile).
- Derin **kod incelemesi yapıldı** (aşağıdaki riskler buradan çıktı).

**Hazır olan YZ modülleri:**
- `detector` (YOLOv8 gerçek/mock), `tracking` (IOU), `speed` (bbox-alan), `plate_ocr`
  (çok-varyant + konsensüs), `driver_state` (EAR/PERCLOS + ROI), `risk` (ağırlıklı),
  `qod_trigger` (A–E motoru), `pipeline` (orkestratör), `schema` (kontrat), `training` (iskelet).

**Henüz YOK:**
- Eğitilmiş özel model (sadece COCO-pretrained / mock).
- Gerçek CAMARA 5G (mock).
- Saha hız kalibrasyonu.
- Windows/CUDA üzerinde doğrulanmış çalıştırma.

---

## 2. Faz Durumu

- **Faz 0 — Prototip temel alındı** ✓ (2026-06-05)
- **Faz 1 — Mimari + derin kod incelemesi** ✓ (2026-06-05)
- **Faz 2 — Windows/CUDA çalıştırma doğrulaması** → BEKLEYEN
- **Faz 3 — Gerçek YOLOv8 (4060) + 3 test videosu ölçümü** → BEKLEYEN
- **Faz 4 — Plaka OCR gerçek (EasyOCR + GPU)** → BEKLEYEN
- **Faz 5 — Sürücü davranışı (telefon gerçek + yorgunluk denemesi)** → BEKLEYEN
- **Faz 6 — Hız kalibrasyonu** → BEKLEYEN
- **Faz 7 — QoD doğrulama (eval: Normal vs Kritik + bant verimliliği)** → BEKLEYEN
- **Faz 8 — Fine-tune (komite verisi gelince)** → BEKLEYEN
- **Faz 9 — Çoklu-araç genişletme** → BEKLEYEN

---

## 3. Karar Günlüğü

- **K-001 (2026-06-05):** Yeni temel = `cleoanka/teknofest-prototip`.
  *Neden:* şartname/transkriptle birebir 3-parçalı mimari (mobil↔backend↔YZ), çalışan
  QoD tetik motoru ve mobil uygulama hazır; eski proje (`C:\teknofest`) referans kalır.
- **K-002 (2026-06-05):** YZ kolu bizim. Sahiplik: `ai/` + `config/settings.py` (YZ eşikleri) + `eval/`.
- **K-003 (2026-06-05):** **Mock-first korunacak** (`AI_MODE=auto`). Kütüphane yoksa sistem mock'a düşmeli, testler yeşil kalmalı.
- **K-004 (2026-06-05):** Çözüm **genel** olacak (her yer/araç). Tek test videosuna özel çözüm yazılmayacak; gizli test seti farklı araç/açı/hava içeriyor.
- **K-005 (2026-06-05):** Kod **her zaman açıklamalı** yazılacak (Türkçe yorum + docstring + neden-yorumu); her adımda PROGRESS/AGENTS güncellenecek.
- **K-006 (2026-06-05):** **Git ile sürüm yönetimi + GitHub'a push.** Her tamamlanan adım kendi
  atomik commit'i olur; sıra: değişiklik → `make test` yeşil → PROGRESS güncel → `git commit` (doküman
  dahil) → `git push`. Commit mesajı Türkçe ve `<alan>: <ne> (neden)` biçiminde. Model ağırlığı/video/
  `.venv`/sır commit'lenmez (`.gitignore`). *Neden:* her adım izlenebilir/geri alınabilir olsun, takım
  GitHub üzerinden senkron kalsın. Detay kural: `AGENTS.md` **K7**.

---

## 4. Açık Konular / Riskler (derin kod incelemesinden)

- **R1 — Platform:** Repo macOS varsayıyor (`run_dev.sh` → `ipconfig getifaddr en0`, MPS, iPhone/Expo).
  Bizim kurulum **Windows + NVIDIA 4060**. Backend çalışır ama `run_dev.sh` doğrudan çalışmaz; venv yolu
  `.venv\Scripts`, gerçek modda cihaz **CUDA** olmalı (`detector._resolve_device` CUDA'yı zaten görüyor).
- **R2 — Eğitilmiş model yok:** `cigarette/seatbelt/headphone` COCO'da yok → `driver_state` bu davranışları
  fine-tune'a kadar **üretemez** (kemer kontrolü kodda kasıtlı kapalı). Sigara/kemer demoda çalışmaz.
- **R3 — Olası kırık test:** `tests/test_pipeline_schema.py::test_pipeline_reads_plate_in_critical` mock modda
  `plate.text is not None` bekliyor; mock PlateReader plaka üretmiyor → bu test mock'ta **düşebilir**.
  Windows'ta `make test` ile teyit edilmeli (sandbox'ta PyPI engelli olduğu için koşulamadı).
- **R4 — Tek-araç varsayımı:** Pipeline en büyük bbox'lı birincil aracı işliyor; şartname "tüm araçlar" istiyor.
- **R5 — Hız kalibrasyonsuz:** `speed_calibration_k=900` keyfi; gerçek km/h anlamlı değil (ihlal eşiği için kullanılıyor, o yeterli).

---

## 5. Sıradaki Adımlar (kısa vade)

0. **Git/GitHub kurulumu (K7):** klasörde repo başlat ve uzak depoya bağla; ilk commit'i at.
   ```
   git init
   git add .
   git commit -m "chore: prototip temel + YZ kolu dokümanları (ilk commit)"
   git branch -M main
   git remote add origin <GitHub-repo-URL>
   git push -u origin main
   ```
   Bundan sonra her adım K7 sırasına göre commit + push edilir.
1. Windows'ta backend'i ayağa kaldır (venv + `uvicorn backend.main:app`), `http://localhost:8000/api/health` 200 mü?
2. `make test` (veya `python -m pytest`) → gerçek test durumunu gör, R3'ü teyit et.
3. `AI_MODE=real` + ultralytics/torch (CUDA 11.8) → 3 test videosunda araç tespiti + FPS.
4. Plaka OCR'ı gerçek EasyOCR ile dene; eski projedeki "34 TC 8532" birikimini taşı.

---

## 6. Haftalık Rapor Formatı (her ajan)

- Bu hafta ne yapıldı?
- Ne çalışıyor (ölçümle)?
- Ne blokluyor?
- Gelecek hafta hedefi?

---

## 7. Çalıştırma Hatırlatması

```
# Backend + web (mock mod yeterli):
AI_MODE=mock  -> kütüphane gerekmez, uçtan uca çalışır
AI_MODE=real  -> ultralytics + easyocr + mediapipe kuruluysa gerçek model

# Test (mock, deterministik):
make test     (Windows: .venv\Scripts\python -m pytest)

# Doğruluk değerlendirmesi (Normal vs Kritik + bant verimliliği):
make eval
```

---

## 8. Git İş Akışı Hatırlatması (K7)

```
# Her tamamlanan adımdan sonra (mock testleri yeşilken):
make test                       # önce yeşil olduğundan emin ol
git pull --rebase               # çakışmayı önle
git add <değişen dosyalar>      # ya da: git add -A
git commit -m "ai: <ne yapıldı> (<neden>)"   # PROGRESS/AGENTS güncellemesi aynı commit'te
git push

# Commit mesajı alanları: ai | config | eval | docs | test | chore
# Commit'lenmez: *.pt model ağırlıkları, videolar, .venv/, .env, sır/token
```
