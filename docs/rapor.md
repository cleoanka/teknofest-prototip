# Rapor & Sunum Kolu Rehberi — Teknik Dokümantasyon & Yarışma Sunumu

> Bu belge rapor ve sunum kolunda çalışanlar için yazıldı. Yarışma değerlendirme
> kriterlerini, teknik rapor yapısını, mimari anlatımı ve sunum stratejisini açıklıyor.

---

## Sen Ne Yapacaksın?

Rapor kolu projenin "sözcüsü"dür. Ne kadar iyi bir sistem kurulursa kurulsun,
jüri bunu anlamazsa puan alınamaz. Teknik çalışmayı anlatılabilir hale getirmek
bu kolun işi.

Somut görevlerin:
- Teknik raporun yazılması ve düzenlenmesi
- Sunum dosyasının (PowerPoint/PDF) hazırlanması
- Sistem mimarisinin diyagram ve görseller ile anlatılması
- Demo senaryosunun tasarlanması
- Yarışma kriterlerine göre eksiklerin takibi
- Teknik terminoloji ile sade anlatım arasında köprü kurmak

---

## Yarışma Değerlendirme Kriterleri (Tablo 1'den)

TEKNOFEST bu projeyi **3 ana kriter** üzerinden puanlıyor:

### Kriter 1 — YZ Analiz Doğruluğu (%40 ağırlık)

Sisteminiz ne kadar doğru tespit yapabiliyor?

Alt başlıklar:
- Araç tespiti doğruluğu (kaç araçtan kaçı bulundu?)
- Plaka okuma başarısı (okunan plakalar gerçek mi?)
- Hız tahmini yakınlığı (gerçeğe ne kadar yakın?)
- Araç içi nesne tespiti (telefon, sigara, kemer)
- Sürücü davranış analizi (yorgunluk, dikkat dağınıklığı)

**Raporda gösterilmesi gerekenler:**
- Test sonuçları tablosu (kaç kare test edildi, kaçı doğru?)
- Confusion matrix veya Precision/Recall değerleri (yapabiliyorsak)
- `make eval` çıktısının ekran görüntüsü veya tablosu
- Model seçim gerekçesi (neden YOLOv8n + YOLOv8s?)
- Sınırlılıklar ve iyileştirme planı

### Kriter 2 — 5G QoD Entegrasyonu (%40 ağırlık)

5G bant genişliği akıllıca kullanılıyor mu?

Alt başlıklar:
- CAMARA QoD API doğru entegre edilmiş mi?
- Bant yalnızca ihtiyaç anında yükseltiliyor mu?
- Bant verimliliği ölçülebiliyor mu?
- QoD tetik mantığı açıklanabiliyor mu?

**Raporda gösterilmesi gerekenler:**
- QoD akış diyagramı (Normal → Kritik → Normal)
- 5 koşulun (A, B, C, D, E) açıklaması
- `bandwidth_efficiency` değeri ve ne anlama geldiği
- CAMARA API çağrılarının kod örnekleri
- Gerçek vs Mock karşılaştırması (ne zaman gerçek API kullanılacak)

### Kriter 3 — Mimari & Modern Pratikler (%20 ağırlık)

Kod kalitesi, tasarım kararları, test kapsamı.

Alt başlıklar:
- Katmanlı mimari var mı?
- Tipler/şemalar iyi tanımlanmış mı?
- Testler var mı? Geçiyor mu?
- Kod okunabilir mi, yapılandırılmış mı?
- Dökümantasyon var mı?

**Raporda gösterilmesi gerekenler:**
- Klasör yapısı ve her klasörün rolü
- Veri akışı diyagramı
- Test raporu (`make test` çıktısı)
- `ARCHITECTURE.md` içeriğinin özeti

---

## Sistemin Anlatımı (Sıfırdan Kurgusu)

### 1. Büyük Resmi Anlat (30 saniye özet)

Jüriye ilk 30 saniyede şunu anlatabilmelisin:

> "Yol kenarına koyduğumuz bir kamera, yapay zeka ile araçları, sürücüleri ve
> plakalarını gerçek zamanlı olarak analiz ediyor. Normal koşullarda 5 Mbps
> düşük bant kullanıyoruz. Tehlikeli bir durum tespit edildiğinde — araç yaklaşıyor,
> sürücü telefon tutuyor veya plaka net okunamamıyorsa — CAMARA QoD API'si
> aracılığıyla 5G şebekesinden 20 Mbps bant genişliği talep ediyoruz.
> Tehlike geçince bant düşüyor. Sürekli yüksek bant değil, sadece gerektiğinde."

### 2. Teknik Akışı Anlat (2 dakika)

```
Kamera Görüntüsü
      ↓
  Ön Yüz (Web/Mobil)
  → Kareyi 640px'e sıkıştır
  → WebSocket ile backend'e gönder (saniyede 5-7 kez)
      ↓
  Backend (FastAPI)
  → Kareyi al ve YZ pipeline'a ilet
      ↓
  YZ Pipeline
  → [A] YOLO ile araç tespit et
  → [B] Takip et (aynı araç mı?)
  → [C] Hız tahmin et
  → [D] Plaka oku (sadece Kritik modda)
  → [E] Sürücü durumunu analiz et (telefon, yorgunluk)
  → [F] Risk skoru hesapla (0-100)
      ↓
  QoD Tetik Motoru
  → 5 koşulu kontrol et (A, B, C, D, E)
  → 2 ardışık pozitif → CAMARA QoD API'ye istek gönder
  → Bant 5 → 20 Mbps
      ↓
  Sonuç → Ön Yüze Gönder
  → Araç kutuları çiz
  → Plaka, hız, risk göster
  → Mod rozetini güncelle (NORMAL / KRİTİK)
      ↓
  Risk ≥ 30 → SQLite'a Kaydet
```

---

## Mimari Diyagram (Metin Olarak)

```
┌────────────────────────────────────────────────────────────────────┐
│                    SİSTEM MİMARİSİ                                 │
│                                                                    │
│  ┌──────────┐    kare (WS)    ┌──────────────────────────────────┐ │
│  │  Mobil   │ ──────────────► │         BACKEND (FastAPI)        │ │
│  │  (Expo)  │ ◄────────────── │                                  │ │
│  └──────────┘   sonuç (WS)    │  ┌─────────────┐ ┌────────────┐ │ │
│                               │  │  YZ Pipeline │ │  QoD Mgr  │ │ │
│  ┌──────────┐    kare (WS)    │  │  ──────────  │ │  ──────── │ │ │
│  │   Web    │ ──────────────► │  │  YOLO detect │ │  Trigger  │ │ │
│  │Dashboard │ ◄────────────── │  │  Tracking    │ │  Engine   │ │ │
│  └──────────┘   sonuç (WS)    │  │  Speed       │ └─────┬─────┘ │ │
│                               │  │  Plate OCR   │       │       │ │
│  ┌──────────┐    GET/POST     │  │  Driver stat │       ▼       │ │
│  │  REST    │ ──────────────► │  │  Risk score  │  CAMARA QoD   │ │
│  │  İstek   │ ◄────────────── │  └─────────────┘  Mock API     │ │
│  └──────────┘     JSON        │                   (POST/DELETE) │ │
│                               │  ┌─────────────┐               │ │
│                               │  │   SQLite DB  │               │ │
│                               │  │   events     │               │ │
│                               │  └─────────────┘               │ │
│                               └──────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

---

## 5G QoD Akış Diyagramı

```
BAŞLA: Normal Mod (5 Mbps)
         │
         ▼
  [500ms döngü] ──► Koşulları Değerlendir
         │
         │  A: Araç hızla yaklaşıyor?
         │  B: Tespit güveni düşük?
         │  C: Plaka okunamıyor?
         │  D: Araç kameraya yakın?
         │  E: Nesne sınır güvende?
         │
    Pozitif mi?
    ┌────┴────┐
   Hayır     Evet
    │          │
    │    Ardışık sayaç +1
    │          │
    │    2. Kez mi?
    │    ┌─────┴──────┐
    │   Hayır         Evet
    │    │              │
    │    │        ┌─────▼──────────────────┐
    │    │        │  KRİTİK MODA GEÇ       │
    │    │        │  POST /camara/qod       │
    │    │        │  Bant: 5 → 20 Mbps     │
    │    │        │  Ağır YOLO + OCR aktif  │
    │    │        └─────┬──────────────────┘
    │    │              │
    │    │        Bırakma Koşulu?
    │    │        ┌──────┴──────────────────────┐
    │    │       Evet (timeout/güven/roi dışı)  Hayır
    │    │        │                              │
    │    │   DELETE /camara/qod/session          │
    │    │   Bant: 20 → 5 Mbps                  │
    │    │        │                              │
    └────┴────────┘◄─────────────────────────────┘
         │
         ▼
  [Sonraki 500ms döngü]
```

---

## Rapor Yapısı Önerisi

Teknik raporun bölümleri şu şekilde kurgulanabilir:

### 1. Yönetici Özeti (1 sayfa)
- Projenin amacı
- Temel özellikler
- Yarışma kriterlerine uyum özeti

### 2. Motivasyon ve Problem Tanımı (1-2 sayfa)
- Yol güvenliği istatistikleri (Türkiye'de trafik kazaları)
- Mevcut sistemlerin sınırlılıkları
- 5G + YZ çözümünün potansiyeli

### 3. Sistem Mimarisi (2-3 sayfa)
- Büyük resim diyagramı
- Üç katman (ön yüz, backend, YZ) ayrıntılı anlatım
- Veri akışı diyagramı
- Teknoloji seçim gerekçeleri

### 4. YZ Bileşenleri (3-4 sayfa)
- YOLOv8 nesne tespiti
- Araç takibi (IOU)
- Hız tahmini yöntemi ve sınırlılıkları
- Plaka OCR + konsensüs yöntemi
- Sürücü davranış analizi (EAR, PERCLOS)
- Risk skoru hesaplama

### 5. 5G QoD Entegrasyonu (2-3 sayfa)
- CAMARA standartları açıklaması
- QoD tetik motoru (5 koşul)
- Bant verimliliği metrikleri
- Normal vs Kritik mod karşılaştırması

### 6. Test ve Değerlendirme (2-3 sayfa)
- Test metodolojisi
- Doğruluk metrikleri
- Bant verimliliği sonuçları
- Test ortamı

### 7. Sonuç ve Gelecek Çalışmalar (1 sayfa)
- Elde edilen sonuçlar
- Sınırlılıklar
- Fine-tune planı
- Gerçek CAMARA API entegrasyon planı

### Ekler
- API referansı
- Kurulum kılavuzu
- Kod listesi (önemli parçalar)

---

## Sunum Slaytları Önerisi (15 dakika)

| Slayt | Konu | Süre |
|-------|------|------|
| 1 | Başlık + Ekip | 30s |
| 2 | Problem: Trafik güvenliği neden önemli? | 1 dk |
| 3 | Çözümümüz: 3 cümle özet | 30s |
| 4 | Sistem mimarisi (büyük resim diyagramı) | 2 dk |
| 5 | YZ bileşenleri (YOLO, OCR, MediaPipe) | 2 dk |
| 6 | 5G QoD akış diyagramı | 2 dk |
| 7 | DEMO — Canlı gösterim | 4 dk |
| 8 | Test sonuçları ve metrikler | 1 dk |
| 9 | Gelecek planı + Fine-tune | 1 dk |
| 10 | Sorular | -- |

---

## Demo Senaryosu

Jüriye canlı demo yaparken şu sırayı takip et:

### Hazırlık (demo öncesi)
```bash
# Backend çalışıyor mu kontrol et:
curl http://localhost:8000/api/health

# Olayları temizle (temiz demo için):
curl -X POST http://localhost:8000/api/clear
```

### Demo Akışı

**1. Sistemi göster (30s)**
- Tarayıcıda `http://localhost:8000/` aç
- "Bu bizim web güvenlik konsolu. Yol kenarı kamera simülasyonu."

**2. Giriş yap (30s)**
- "Önce sessiz SIM doğrulama — SMS veya kod yok"
- Login butonuna bas → "✓ Doğrulandı" göster

**3. Kamerayı başlat (30s)**
- "Kamerayı Başlat"a tıkla
- "Kamera açıldı, saniyede 7 kare backend'e gönderiliyor"
- Sol üstte "Canlı" yeşil noktası göster

**4. Normal modu anlat (1 dk)**
- "Şu an NORMAL mod — 5 Mbps, hafif model"
- Tespit kutularını göster
- "Araç yokken veya tehlike yokken bant düşük"

**5. Kritik mod tetikle (1 dk)**
- Kameraya yakın nesne getir veya hareket yap
- QoD tetiklenince: "Bakın — KRİTİK moda geçti, 20 Mbps"
- "CAMARA QoD API'ye POST isteği gönderildi"
- `/api/qod/status` göster (bandwidth_efficiency)

**6. Metrikleri göster (30s)**
- Sağ panelde QoD durumu, bant verimliliği
- "Zamanın %82'sinde düşük bantta kaldık"

**7. Olaylar listesi (30s)**
- `/api/events` → "Risk skoru 30+ olan olaylar SQLite'a kaydedildi"

---

## Önemli Sayılar ve Metrikler (Raporda Kullan)

### Sistem Performansı
- WebSocket gecikmesi: ~50-100ms (lokal ağda)
- Kare işleme süresi: 50-200ms (GPU olmadan CPU)
- Normal mod FPS: ~6-7 kare/saniye
- QoD değerlendirme aralığı: 500ms

### Bant Genişliği
- Normal mod: 5 Mbps
- Kritik mod: 20 Mbps
- Tasarruf oranı (bant verimliliği): `1 - (kritik_süre / toplam_süre)`
- Hedef: %80+ düşük bantta kalış

### YZ Modelleri
- Normal: YOLOv8n (nano) — 3.2M parametre, ~6ms/kare (GPU)
- Kritik: YOLOv8s (small) — 11.2M parametre, ~12ms/kare (GPU)
- COCO sınıf sayısı: 80
- Kullandığımız: araç, insan, telefon (3 kritik sınıf)

### Test Kapsamı
- Toplam test sayısı: 38
- Test modu: Mock (model gerektirmez)
- Kapsam: API, WebSocket, YZ mantığı, QoD tetik, risk, hız

---

## Sıkça Sorulan Sorular (Jüriden Gelebilecekler)

**S: Gerçek 5G ile test ettiniz mi?**
C: Gerçek CAMARA QoD API Turkcell sandbox erişimi gerektiriyor. Aynı API standardını
uygulayan mock ile geliştirdik. Gerçek entegrasyon için `backend/camara/qod.py`
dosyasında sadece HTTP çağrı adresleri değiştirilmeli, tüm mantık aynı kalır.

**S: YZ modeli ne kadar doğru?**
C: COCO ön-eğitimli YOLOv8 araç tespitinde %80-95 doğruluk sağlıyor (standart
test setleri). Komite verisini alınca `ai/training/` ile fine-tune yapıp
proje-spesifik sınıflar için (sigara, kemer, kulaklık) doğruluğu artıracağız.

**S: Plaka okuma ne kadar güvenilir?**
C: EasyOCR ile iyi ışıkta %70+ güvenle okuma yapılabiliyor. Düşük güvenli okumalar
filtreleniyor (güven < 0.70 → gösterilmiyor). Sistem asla yanlış plakayı doğruymuş
gibi göstermiyor.

**S: Hız tespiti calibrasyonlu mu?**
C: Kalibrasyonsuz bbox-alan modeli kullanılıyor — radar veya GPS yok. Bu
kalibrasyonlu bir tahmin değil, göreceli hareket hızı. Gerçek sistemde LIDAR
veya kalibrasyon referansları kullanılır. Şu an QoD tetikleme (yaklaşma tespiti)
için yeterince doğru.

**S: Kullanıcı gizliliği nasıl korunuyor?**
C: Kamera görüntüleri backend'de saklanmıyor — sadece anlık işleniyor. Olaylar
veritabanında yalnızca meta veri (plaka, hız, risk skoru) tutuluyor, ham görüntü
yok. CAMARA Number Verification sessiz SIM doğrulama kullandığından kullanıcı
kimlik bilgisi toplanmıyor.

**S: Sistem gerçek zamanlı mı?**
C: Saniyede 6-7 kare, ~100ms gecikmeyle işleniyor. Gerçek zamanlı güvenlik
sistemleri için kabul edilebilir (kamera 30fps ise her ~5. kare analiz ediliyor).

---

## Görseller İçin Öneriler

Raporda kullanmak üzere şu ekran görüntülerini al:

1. **Sistem sağlık ekranı** → `http://localhost:8000/api/health`
2. **Web konsolu — Normal mod** → Kamera açık, NORMAL rozetli
3. **Web konsolu — Kritik mod** → KRİTİK rozetli, kırmızı çerçeve
4. **Olay listesi** → `/api/events` API cevabı
5. **QoD durum** → `/api/qod/status` — bandwidth_efficiency değeri
6. **Test koşusu** → `make test` terminal çıktısı (38 test geçiyor)
7. **Eval raporu** → `make eval` çıktısı

---

## Teknik Terminoloji Sözlüğü (Rapor İçin)

Raporunuzda kullanabileceğiniz resmi terminoloji:

| Kullandığımız | Resmi Terim |
|---------------|------------|
| Bant genişliği artırma | Quality of Service (QoS) provisioning |
| Tespit güveni | Confidence score |
| Plaka okuma | License Plate Recognition (LPR) |
| Sürücü yorgunluk tespiti | Driver drowsiness detection |
| Göz açıklık oranı | Eye Aspect Ratio (EAR) |
| Göz kapanma yüzdesi | PERCLOS (Percentage of Eyelid Closure) |
| Bant verimliliği | Bandwidth utilization efficiency |
| Uçtan uca gecikme | End-to-end latency |
| Anlık veri aktarımı | Real-time data streaming |
| Nesne tespiti | Object detection |
| Nesne takibi | Object tracking |
| Kesişim oranı | Intersection over Union (IoU) |
| Kalibrasyonsuz hız tahmini | Monocular speed estimation |

---

## Takvim Önerisi

| Hafta | Görev |
|-------|-------|
| 1 | Mevcut sistemin tam anlatımını yaz (mimari, akış diyagramları) |
| 2 | YZ bileşenlerinin teknik açıklamasını tamamla |
| 3 | 5G QoD entegrasyon bölümünü yaz |
| 4 | Test sonuçlarını al ve tabloya dök |
| 5 | Sunum slaytları hazırla |
| 6 | Demo senaryosu prova, rapor son gözden geçirme |

---

## Faydalı Kaynaklar

- [CAMARA Proje Resmi Sitesi](https://camaraproject.org/)
- [CAMARA QoD API Dökümantasyonu](https://github.com/camaraproject/QualityOnDemand)
- [YOLOv8 Teknik Raporu (Ultralytics)](https://docs.ultralytics.com/)
- [EAR Yorgunluk Tespiti Makalesi — Soukupova & Cech 2016](https://vision.fe.uni-lj.si/cvww2016/proceedings/papers/05.pdf)
- [PERCLOS Açıklaması](https://www.nhtsa.gov/sites/nhtsa.gov/files/perclos-a-valid-psychophysiological-measure-of-drowsiness.pdf)
- [Proje ARCHITECTURE.md](../ARCHITECTURE.md) — Sistemin teknik mimarisi
