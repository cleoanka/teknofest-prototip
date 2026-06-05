# Proje Temelleri — Herkesin Okuması Gereken Giriş Rehberi

> Bu dosyayı projeye yeni katılan herkes okumalı. Teknik bilgi gerekmez.
> Aşağıda projeyi ve nasıl çalıştığını mümkün olduğunca sade anlatmaya çalıştım.

---

## Bu Proje Ne Yapıyor? (Tek Cümle)

Yol kenarına veya araç içine kurulan bir kamera, yapay zeka ile görüntüyü analiz eder;
tehlikeli bir durum gördüğünde **5G ağ hızını otomatik olarak artırır** ve güvenlik
ekibine anlık uyarı gönderir.

---

## Neden Yaptık? (Yarışma Bağlamı)

Bu proje **TEKNOFEST 2026** yarışması için, **Turkcell'in 5G & Yapay Zeka ile Akıllı Yol
Güvenliği** dalına katılmak üzere yapılıyor.

Yarışma bize şunu soruyor:

> "Bir yol güvenlik sistemi kur. Araçları, sürücüleri ve plakalarını tespit et.
> Tehlike anında **CAMARA QoD API** ile bant genişliğini artır.
> Ama bant genişliğini her zaman yüksek tutma — sadece gerektiğinde kullan."

Bu üç şeyi ne kadar iyi yaptığımıza göre puan alıyoruz.

---

## Sistemin Parçaları (Büyük Resim)

Projeyi bir fabrika gibi düşün. Fabrikada üç ana bölüm var:

```
┌─────────────────────────────────────────────────────────┐
│                     SİSTEM AKIŞI                        │
│                                                         │
│  📱 Mobil/Web    ──kare──►  🖥️ Backend   ──kare──►  🤖 YZ  │
│  (ön yüz)       ◄──sonuç──  (sunucu)    ◄──sonuç──  (ai) │
└─────────────────────────────────────────────────────────┘
```

### 1. Ön Yüz (Frontend) — Kullanıcının Gördüğü Ekran
- Web tarayıcıda açılan **güvenlik konsolu** (`frontend/`)
- iPhone/Android uygulaması (`mobile/`)
- Kameradan görüntü alır, **saniyede 5-7 kare** backend'e yollar
- Sonuçları ekranda gösterir (kutular, plaka, hız, risk skoru)

### 2. Backend (Sunucu) — Projenin Beyni
- `backend/` klasöründe yaşar
- Her gelen kareyi YZ'ye gönderir
- YZ'nin sonuçlarını alır, kaydeder, ön yüze gönderir
- QoD sistemini yönetir (bant genişliği kararı)
- REST API + WebSocket ile konuşur

### 3. YZ (Yapay Zeka) — Görüntüyü Anlayan Kısım
- `ai/` klasöründe yaşar
- Her kareyi analiz eder:
  - Araç var mı? Nerede?
  - Plaka ne?
  - Hız kaç km/h?
  - Sürücü telefon tutuyor mu?
  - Risk skoru kaç?

---

## 5G QoD Ne Demek? (Sıfırdan Açıklama)

**QoD = Quality on Demand = İsteğe Bağlı Kalite**

Normal hayatta internete bağlandığında bir hız alırsın. Ama bazı durumlarda
"şu an 5 dakika için bana 4 kat daha hızlı internet ver" diyebilirsin.
İşte bu QoD.

Biz bunu yol güvenliğinde şöyle kullanıyoruz:

```
Durum 1 — Normal (Araç uzakta):
  Kamera 480p görüntü gönderir → 5 Mbps yeterli

Durum 2 — Kritik (Araç yaklaşıyor, tehlike var):
  Sistem CAMARA API'sine "bana 20 Mbps ver" der
  Kamera 1080p görüntüye geçer
  Daha detaylı analiz başlar
  Tehlike geçince bant tekrar 5 Mbps'e düşer
```

**Neden önemli?** Yarışmada puan almak için bant genişliğini sadece gerektiğinde
kullanmamız gerekiyor. Sürekli yüksek bant = puan kaybı.

---

## Proje Klasör Yapısı

```
teknofest-prototip/
│
├── ai/                    ← Yapay Zeka kolu
│   ├── detector.py        Araç tespiti (YOLOv8)
│   ├── plate_ocr.py       Plaka okuma
│   ├── speed.py           Hız tahmini
│   ├── driver_state.py    Sürücü durumu (telefon, yorgunluk)
│   ├── risk.py            Risk skoru hesaplama
│   ├── pipeline.py        Hepsini bir araya getiren orkestratör
│   ├── qod_trigger.py     Ne zaman bant artırılacağına karar verir
│   └── training/          Model eğitimi
│
├── backend/               ← API kolu
│   ├── main.py            Sunucunun ana dosyası
│   ├── qod_manager.py     QoD yönetimi
│   ├── db.py              Veritabanı işlemleri
│   └── camara/            CAMARA API simülasyonu
│
├── frontend/              ← Web arayüzü (entegrasyon kolu)
│   ├── index.html         Ana sayfa
│   ├── app.js             Kamera + WebSocket kodu
│   └── styles.css         Görsel tasarım
│
├── mobile/                ← Mobil kol
│   ├── App.tsx            Ana uygulama
│   └── src/
│       ├── screens/       Ekranlar (Login, Dashboard, EventDetail)
│       └── api/           Backend bağlantısı
│
├── tests/                 ← Test dosyaları
├── docs/                  ← Bu belgeler (şu an buradasın)
├── config/settings.py     Tüm ayarlar tek yerde
└── requirements.txt       Python paketleri
```

---

## Kim Ne Yapıyor? (Kol Görevleri)

| Kol | Sorumluluk | Dosyalar |
|-----|-----------|---------|
| **YZ** | Araç/plaka/sürücü tespiti, risk skoru | `ai/` |
| **API** | Sunucu, veri akışı, CAMARA entegrasyonu | `backend/` |
| **Mobil** | iPhone/Android uygulaması | `mobile/` |
| **Entegrasyon** | Parçaları birleştirme, web arayüzü, testler | `frontend/`, `tests/` |
| **Rapor** | Teknik rapor, sunum, dokümantasyon | `docs/`, sunumlar |

---

## Sistemi Nasıl Çalıştırırsın?

### Backend'i başlatmak (YZ + Sunucu):

```bash
# Proje klasörüne gir
cd teknofest-prototip

# Çalıştır (ilk seferde bağımlılıkları indirir, biraz sürer)
./run_dev.sh
```

Çıktıda şunu görürsen başarılı:
```
http://localhost:8000/ adresinde çalışıyor
```

Tarayıcıda `http://localhost:8000/` yaz, açılmalı.

### Sadece test çalıştırmak için:

```bash
make test
```

---

## Kavramlar Sözlüğü

Projede çok kullanılan teknik kelimelerin sade açıklamaları:

| Kelime | Ne Demek |
|--------|----------|
| **API** | İki yazılımın birbiriyle konuşması için kurallar seti. "Menü" gibi düşün — ne isteyebileceğini listeler. |
| **WebSocket** | Sürekli açık kalan bir bağlantı. Normal internet gibi değil; "kapıyı açık bırak, haberler gelince bana söyle" gibi. |
| **REST** | API'nin bir türü. Her şey URL'lerle ve HTTP istekleriyle yapılır. |
| **YOLOv8** | Gerçek zamanlı nesne tespit yapay zeka modeli. Bir görüntüde "bu kare, bu nesne" der. |
| **OCR** | Optical Character Recognition — görüntüdeki yazıyı okuma. Plakayı okumak için kullanılıyoruz. |
| **MediaPipe** | Google'ın yüz ve vücut takip kütüphanesi. Sürücünün gözlerini takip etmek için. |
| **FastAPI** | Python ile hızlı API yazmak için kullanılan bir araç (framework). |
| **React Native** | Hem iOS hem Android için uygulama yazmayı sağlayan araç. |
| **Expo** | React Native'i kolaylaştıran ek araçlar paketi. |
| **TypeScript** | JavaScript'e tip kontrolü eklenmiş hali. Hatalar önceden yakalanır. |
| **SQLite** | Küçük, dosya tabanlı veritabanı. Olayları kaydetmek için kullanıyoruz. |
| **QoD** | Quality on Demand — isteğe bağlı ağ kalitesi. |
| **CAMARA** | 5G şebeke API'lerini standartlaştıran açık kaynak proje. |
| **Mock** | Gerçek olmayan, test için taklit eden. "Mock CAMARA" = gerçek 5G ağı yerine simülasyon. |
| **Kare (Frame)** | Videonun tek bir fotoğrafı. Saniyede ~30 kare geliyor. |
| **Bbox** | Bounding Box — tespit edilen nesnenin etrafını çizen dikdörtgen. |
| **Confidence** | Modelin "ne kadar emin olduğu" (0-1 arası). 0.85 = %85 emin. |
| **Profile** | Normal veya Kritik mod. Kritik'te daha ağır model çalışır. |

---

## Proje Nasıl Çalışıyor? (Adım Adım)

1. **Kamera görüntüyü alır** → Telefon ya da bilgisayar kamerası açık
2. **Ön yüz kareyi sıkıştırır** → 640px genişliğe düşürür, JPEG yapar
3. **WebSocket ile gönderir** → Backend'e saniyede 5-7 kez
4. **Backend kareyi alır** → `backend/main.py`'deki `/ws/ingest` noktasına gelir
5. **YZ pipeline çalışır** → `ai/pipeline.py` hepsini sırayla işler:
   - YOLO ile araç tespit et
   - Takip et (aynı araç mı?)
   - Hızı hesapla
   - Plakayı oku (sadece kritik modda)
   - Sürücü durumunu kontrol et
   - Risk skorunu hesapla
6. **QoD motoru karar verir** → "Kritik moda geç mi, geçme mi?"
7. **Sonuç ön yüze döner** → JSON olarak WebSocket üzerinden
8. **Ön yüz ekrana çizer** → Kutular, plaka, hız, risk gösterilir
9. **Olay kaydedilir** → Risk skoru 30+ ise SQLite'a yazılır

---

## Dikkat Edilmesi Gerekenler

- **`.env` dosyasını asla GitHub'a yükleme.** Bu dosya API anahtarları gibi gizli bilgiler içerir.
- **`.venv/` klasörü de yüklenmemeli.** `requirements.txt` zaten neyin gerekli olduğunu söylüyor.
- **`model.pt` dosyaları da yüklenmemeli.** Bunlar büyük model dosyaları.
- **Her kol kendi dalında (branch) çalışmalı**, `main` doğrudan değiştirilmemeli.

---

## Sık Sorulan Sorular

**S: Gerçek 5G ağım yok, nasıl test edeceğim?**
C: CAMARA API'si mock (simülasyon) modda çalışıyor. Gerçek 5G gerekmez. Sistem kendi kendine simüle ediyor.

**S: YOLOv8 modeli yoksa ne olur?**
C: Sistem otomatik olarak "mock" moda geçer. Gerçek tespit yapamaz ama tüm sistem çalışmaya devam eder, testler geçer.

**S: Koda hiç dokunmadan testleri nasıl çalıştırırım?**
C: `make test` yaz. Otomatik olarak her şeyi mock modda çalıştırır.

**S: Hangi Python sürümü gerekli?**
C: Python 3.10 veya üzeri (3.13'te test edildi).

**S: Node.js gerekiyor mu?**
C: Sadece mobil uygulamayı çalıştırmak için (`mobile/` klasörü). Backend için gerekmez.

---

## Daha Fazla Bilgi İçin

- YZ kolundaysanız: [`docs/yz.md`](yz.md)
- API kolundaysanız: [`docs/api.md`](api.md)
- Mobil kolundaysanız: [`docs/mobil.md`](mobil.md)
- Entegrasyon kolundaysanız: [`docs/entegrasyon.md`](entegrasyon.md)
- Rapor/Sunum kolundaysanız: [`docs/rapor.md`](rapor.md)
