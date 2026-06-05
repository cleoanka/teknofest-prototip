# Mobil Uygulama (Expo / React Native)

Şartnamenin final aşamasında istenen **ana ön yüz**: mobil uygulama telefonun
kamerasından canlı görüntü alır, backend YZ servisine yollar, tespit sonuçlarını
ekranda gösterir. Sessiz SIM doğrulama (CAMARA Number Verification) ile giriş yapılır.

## Ekranlar
- **LoginScreen** — Number Verification ile sessiz doğrulama (SMS yok).
- **DashboardScreen** — canlı kamera + overlay kutular + QoD durum + araç/plaka + risk.
- **EventDetailScreen** — kaydedilmiş ihlal olayının detayı.

## Çalıştırma
```bash
cd mobile
npm install
# src/api/client.ts içindeki API_BASE'i Mac'inin LAN IP'siyle değiştir:
#   ipconfig getifaddr en0     ->  ör. http://192.168.1.20:8000
npx expo start
```
Telefonda **Expo Go** ile QR'ı okut (telefon ve Mac aynı Wi-Fi'de olmalı).
Backend'i ayrıca çalıştır: `python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`.

## Notlar
- iOSّte `NSCameraUsageDescription` ayarlı (app.json).
- Kare gönderimi `takePictureAsync` ile ~5 FPS; backend QoD döngüsüyle uyumlu.
- Final'de `API_BASE`, Turkcell 5G uç noktasına yönlendirilecek; sözleşme değişmez.
