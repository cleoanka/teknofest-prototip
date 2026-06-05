# Mobil Kol Rehberi — iOS & Android Uygulama Geliştirme

> Bu belge mobil uygulama kolunda çalışanlar için yazıldı. React Native, Expo,
> TypeScript ve kamera/WebSocket entegrasyonunu açıklıyor.

---

## Sen Ne Yapacaksın?

Mobil kol projenin "el" kısmıdır. Kullanıcı ne görür, nasıl giriş yapar,
kamera nasıl açılır, sonuçlar ekranda nasıl gösterilir — bunların hepsi sende.

Somut görevlerin:
- Giriş ekranı (SIM doğrulama akışı)
- Kamera açma ve kare yakalama
- WebSocket bağlantısı ile backend'e kare gönderme
- Gelen sonuçları (araç, plaka, risk) ekranda gösterme
- iOS ve Android uyumluluğunu sağlama

---

## Önce Bunları Öğren

1. **JavaScript temelleri** — değişken, fonksiyon, `=>` arrow function, `async/await`
   - Kaynak: javascript.info (Türkçe çevirisi var)

2. **TypeScript nedir** — JavaScript'te tip sistemi
   - Şimdilik sadece şunu bil: `const x: string = "merhaba"` — değişkenin tipi önceden belirtilir
   - Kaynak: TypeScript'in "5 Dakikada TypeScript" rehberi

3. **React temelleri** — bileşen (component), state, props kavramı
   - Kaynak: react.dev — "Quick Start" bölümü, Türkçe içerik de var

4. **React Native** — React ama telefon için
   - Web'deki `<div>` yerine `<View>`, `<p>` yerine `<Text>` kullanılır
   - Mantık aynı, platform farklı

5. **Expo** — React Native'i 10 kat kolaylaştıran araçlar seti
   - Kamera, konum, bildirim gibi "native" özellikleri paket olarak sunar
   - Fiziksel cihazda test için Expo Go uygulamasını telefonuna kur

---

## Proje Yapısı

```
mobile/
├── App.tsx                    Ana uygulama giriş noktası
├── app.json                   Expo/uygulama konfigürasyonu
├── package.json               Bağımlılıklar (npm paketleri)
├── babel.config.js            Transpiler ayarları (dokunmana gerek yok)
├── tsconfig.json              TypeScript ayarları (dokunmana gerek yok)
└── src/
    ├── api/
    │   └── client.ts          Backend ile HTTP/WebSocket bağlantısı
    ├── screens/
    │   ├── LoginScreen.tsx    Giriş ekranı (SIM doğrulama + sunucu IP)
    │   ├── DashboardScreen.tsx Ana ekran (kamera + sonuçlar)
    │   └── EventDetailScreen.tsx Olay detay ekranı
    └── types.ts               TypeScript veri tipleri
```

---

## Uygulama Nasıl Başlar? (`App.tsx`)

`App.tsx` uygulamanın ana dosyasıdır. Hangi ekranın görüneceğini kontrol eder.

```typescript
type Screen = "login" | "dashboard" | "detail";

export default function App() {
  const [screen, setScreen] = useState<Screen>("login");  // başlangıçta login ekranı
  const [token, setToken] = useState<string | null>(null);

  return (
    <SafeAreaView style={styles.root}>
      {screen === "login" && (
        <LoginScreen
          onSuccess={(t) => { setToken(t); setScreen("dashboard"); }}
        />
      )}
      {screen === "dashboard" && (
        <DashboardScreen
          onOpenEvent={(ev) => { setSelectedEvent(ev); setScreen("detail"); }}
          onLogout={() => { setToken(null); setScreen("login"); }}
        />
      )}
      {screen === "detail" && (
        <EventDetailScreen event={selectedEvent} onBack={() => setScreen("dashboard")} />
      )}
    </SafeAreaView>
  );
}
```

Bu yapıya **kendi ekran yöneticisi** denir. Navigation kütüphanesi kullanmak
yerine basit bir state ile ekranlar arası geçiş yapılıyor.

---

## Giriş Ekranı (`LoginScreen.tsx`)

### Ne Yapıyor?

1. Kullanıcıdan **sunucu IP adresi** alır (Android için kritik)
2. **Cihaz token** ve **telefon numarası** alır
3. Backend'e `/camara/number-verification:verify` isteği atar
4. Başarılıysa `onSuccess(token)` ile Dashboard'a geçiş yapar

### Sunucu IP Neden Gerekli?

Telefon ve bilgisayar aynı Wi-Fi'de olsa bile, telefon `localhost:8000`'e gidemez.
"localhost" = "bu cihazın kendisi" anlamına gelir. Telefon Mac'i kastetmez.

Çözüm: Mac'in ağ içindeki IP adresini kullan:

```bash
# Mac'te terminalde çalıştır:
ipconfig getifaddr en0
# Örnek çıktı: 192.168.1.35
```

Sonra uygulamada "Sunucu Adresi" kutusuna `192.168.1.35:8000` yaz.

### Kod Mantığı

```typescript
const verify = async () => {
  setApiBase(serverHost);  // client.ts'e sunucu adresini bildir
  try {
    const res = await silentVerify(deviceToken, phone);  // HTTP isteği
    if (res.devicePhoneNumberVerified) {
      onSuccess(res.token);  // Başarılı → dashboard'a geç
    }
  } catch (e) {
    setStatus("Bağlantı hatası");  // Hata → göster
  }
};
```

---

## Ana Ekran (`DashboardScreen.tsx`)

### Ne Yapıyor?

1. **Kamera iznini** kontrol eder/ister
2. **WebSocket bağlantısı** açar
3. Her saniyede 5 kez kare yakalar → base64 JPEG → WebSocket üzerinden gönderir
4. Gelen `FrameResult` verisiyle ekranı günceller:
   - Kamera görüntüsü üzerine tespit kutuları çizer
   - Plaka, hız, araç tipi gösterir
   - Risk skoru ve faktörlerini gösterir
   - QoD modunu (NORMAL/KRİTİK) gösterir

### Kamera İzni

```typescript
const [perm, requestPerm] = useCameraPermissions();

useEffect(() => {
  if (!perm?.granted) requestPerm();  // İzin yoksa iste
}, []);

if (!perm?.granted) {
  return <View><Text>Kamera izni gerekli…</Text></View>;
}
```

### WebSocket Bağlantısı

```typescript
useEffect(() => {
  const ws = new WebSocket(getWsIngest());  // ws://192.168.1.35:8000/ws/ingest
  ws.onopen = () => setConnected(true);
  ws.onclose = () => setConnected(false);
  ws.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (!data.error) setResult(data);  // Ekranı güncelle
  };

  const timer = setInterval(capture, 1000 / SEND_FPS);  // 5 FPS gönder
  return () => { clearInterval(timer); ws.close(); };  // Temizleme
}, []);
```

### Kare Yakalama ve Gönderme

```typescript
const capture = async () => {
  const pic = await camRef.current.takePictureAsync({
    base64: true,    // base64 string olarak al
    quality: 0.4,    // %40 kalite = küçük dosya = hızlı
    skipProcessing: true  // iOS'ta işlem atla = daha hızlı
  });

  ws.send(JSON.stringify({
    frame: "data:image/jpeg;base64," + pic.base64
  }));
};
```

### Tespit Kutularını Çizmek

Backend'den gelen her tespit için gerçek kamera koordinatlarına dönüştürerek
kutu çizilir:

```typescript
{result.detections.map((d, i) => (
  <View key={i} style={{
    position: "absolute",
    left: d.bbox.x1 * scaleX,
    top: d.bbox.y1 * scaleY,
    width: (d.bbox.x2 - d.bbox.x1) * scaleX,
    height: (d.bbox.y2 - d.bbox.y1) * scaleY,
    borderWidth: 2,
    borderColor: d.label === "vehicle" ? "#2f7bff"    // mavi = araç
               : d.label === "phone" ? "#ff4d5e"      // kırmızı = telefon
               : "#2ecc71",                            // yeşil = diğer
  }}>
    <Text>{d.label} {(d.confidence * 100)|0}%</Text>
  </View>
))}
```

`scaleX/scaleY`: Kare 640px genişliğinde gönderiliyor ama ekran farklı boyutta.
Bu oran farkını düzeltmek için kullanılır.

---

## Backend Bağlantısı (`src/api/client.ts`)

```typescript
let _base = "http://192.168.1.20:8000";  // Varsayılan sunucu adresi

export function setApiBase(host: string) {
  _base = host.startsWith("http") ? host : `http://${host}`;
}

export function getWsIngest() {
  return _base.replace(/^http/, "ws") + "/ws/ingest";
  // http://... → ws://...
}
```

Neden `http` → `ws` dönüşümü?
WebSocket'in kendi protokolü var: `ws://` (şifreli versiyonu `wss://`).
`new WebSocket("ws://192.168.1.35:8000/ws/ingest")` şeklinde bağlanıyoruz.

---

## Veri Tipleri (`src/types.ts`)

TypeScript'te bir veri tipi tanımlaması şöyle görünür:

```typescript
export interface BBox {
  x1: number;  // sol kenar
  y1: number;  // üst kenar
  x2: number;  // sağ kenar
  y2: number;  // alt kenar
}

export interface Detection {
  label: string;       // "vehicle", "phone", "person"
  confidence: number;  // 0.0 - 1.0
  bbox: BBox;
  track_id?: number;   // ? = isteğe bağlı
}

export interface FrameResult {
  frame_id: number;
  mode: "NORMAL" | "CRITICAL";
  detections: Detection[];
  vehicle: Vehicle;
  driver: DriverState;
  risk: RiskAssessment;
  qod: QoDStatus;
  fps: number;
  latency_ms: number;
}
```

Bu tipler hem hataları önceden yakalar hem de editörde otomatik tamamlama sağlar.
Backend'den farklı bir alan adı gelirse TypeScript hata verir — tutarsızlık anında görülür.

---

## `app.json` — Uygulama Konfigürasyonu

```json
{
  "expo": {
    "name": "Akıllı Yol Güvenliği",
    "slug": "yol-guvenligi-mobil",
    "version": "1.0.0",

    "ios": {
      "bundleIdentifier": "com.teknofest2026.yolguvenligi",
      "infoPlist": {
        "NSCameraUsageDescription": "Canlı yol güvenliği analizi için kamera gerekli.",
        "NSLocalNetworkUsageDescription": "Backend sunucusuna bağlanmak için gerekli."
      }
    },

    "android": {
      "package": "com.teknofest2026.yolguvenligi",
      "minSdkVersion": 24,          // Android 7.0 minimum
      "targetSdkVersion": 34,       // Android 14 hedef
      "usesCleartextTraffic": true, // HTTP (HTTPS değil) izni — geliştirme için
      "permissions": [
        "android.permission.CAMERA",
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.ACCESS_WIFI_STATE"
      ]
    },

    "plugins": [
      ["expo-camera", {
        "cameraPermission": "Canlı analiz için kamera erişimi gereklidir."
      }]
    ]
  }
}
```

**`usesCleartextTraffic: true` neden var?**
Android 9+'dan itibaren şifresiz (HTTP) trafik varsayılan olarak engelleniyor.
Biz geliştirme sırasında HTTPS olmadan çalışıyoruz (yerel ağ). Bu ayar izin veriyor.
Production'da HTTPS'e geçilince kaldırılmalı.

---

## Uygulamayı Çalıştırmak

### Geliştirme ortamı hazırlığı (bir kere yapılır):

```bash
# Node.js kurulu olmalı (nodejs.org)
# Expo Go uygulamasını iOS App Store veya Google Play'den telefona yükle

cd mobile
npm install  # Bağımlılıkları indir
```

### Başlatmak:

```bash
npx expo start
```

Terminal'de bir QR kodu çıkacak. Telefonla:
- **iOS**: Kamera uygulamasını aç, QR'ı okut
- **Android**: Expo Go uygulamasını aç, QR'ı tara

Uygulama telefonunda açılır. Kod değiştirince uygulama otomatik güncellenir.

### Sadece Android başlatmak:

```bash
npx expo start --android
# veya:
npm run android
```

### Sadece iOS başlatmak:

```bash
npx expo start --ios
# veya:
npm run ios
```

---

## React Native'de Stil Sistemi

Web'deki CSS yerine JavaScript nesneleriyle stil yazılır:

```typescript
// Web CSS:
// .card { background-color: #131a2e; border-radius: 14px; padding: 16px; }

// React Native:
const styles = StyleSheet.create({
  card: {
    backgroundColor: "#131a2e",  // camelCase kullan
    borderRadius: 14,             // px yok, sayı yeterli
    padding: 16,
    marginHorizontal: 16,
    marginBottom: 14,
  }
});

// Kullanım:
<View style={styles.card}>
  <Text>İçerik</Text>
</View>
```

Temel bileşenler:

| Web | React Native |
|-----|-------------|
| `<div>` | `<View>` |
| `<p>`, `<h1>`, `<span>` | `<Text>` |
| `<input>` | `<TextInput>` |
| `<button>` | `<TouchableOpacity>` |
| `<img>` | `<Image>` |
| `<ul>/<li>` | `<FlatList>` |

---

## Flex Layout (Yerleşim Düzeni)

React Native'de tüm yerleşim **Flexbox** ile yapılır.

```typescript
// Yatay yan yana:
{ flexDirection: "row" }

// Dikey alt alta (varsayılan):
{ flexDirection: "column" }

// Ortala:
{ alignItems: "center", justifyContent: "center" }

// Boş alanı doldur:
{ flex: 1 }
```

---

## useState ve useEffect (React Temelleri)

**useState** = ekran yenilenince değişen veri

```typescript
const [connected, setConnected] = useState(false);
// connected = şu anki değer
// setConnected = değeri değiştiren fonksiyon
// false = başlangıç değeri

// Kullanım:
setConnected(true);  // değişir, ekran yeniden çizilir
```

**useEffect** = belirli bir şey olduğunda çalışan kod

```typescript
// Bileşen ilk yüklendiğinde çalış:
useEffect(() => {
  connectWebSocket();
}, []);  // [] = sadece bir kez

// connected değiştiğinde çalış:
useEffect(() => {
  console.log("Bağlantı durumu:", connected);
}, [connected]);
```

---

## Yeni Bir Ekran Eklemek

Örneğin "İstatistikler" ekranı eklemek:

**1. Ekran dosyası oluştur** (`src/screens/StatsScreen.tsx`):

```typescript
import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet } from "react-native";
import { fetchEvents } from "../api/client";

export default function StatsScreen({ onBack }: { onBack: () => void }) {
  const [total, setTotal] = useState(0);

  useEffect(() => {
    fetchEvents(0, 1000).then(events => setTotal(events.length));
  }, []);

  return (
    <View style={s.root}>
      <Text style={s.title}>Toplam Olay: {total}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b1020", padding: 20 },
  title: { color: "#e6ecff", fontSize: 24 },
});
```

**2. App.tsx'e ekle:**

```typescript
type Screen = "login" | "dashboard" | "detail" | "stats";  // yeni ekran tipi

// Dashboard'da butona ekle:
onOpenStats={() => setScreen("stats")}

// Ekran render:
{screen === "stats" && (
  <StatsScreen onBack={() => setScreen("dashboard")} />
)}
```

---

## iOS ve Android Farklılıkları

React Native büyük ölçüde ikisi için aynı kod çalışır, ama bazı farklılıklar var:

| Özellik | iOS | Android |
|---------|-----|---------|
| İzin isteme | `Info.plist` metin gerekir | Manifest izinleri gerekir |
| Kamera kalitesi | `takePictureAsync` kalitesi iOS'ta daha iyi | Cihaza göre değişir |
| HTTP | Varsayılan engeller (ATS) | Varsayılan izin verir |
| Geri butonu | Yok (jest ile) | Fiziksel/sanal geri butonu var |
| Bildirimler | APNs sistemi | FCM sistemi |

Platforma göre farklı kod yazmak gerekirse:

```typescript
import { Platform } from "react-native";

const message = Platform.OS === "ios"
  ? "iOS'ta çalışıyor"
  : "Android'de çalışıyor";

// Veya:
const styles = StyleSheet.create({
  container: {
    paddingTop: Platform.OS === "android" ? 25 : 0,  // Android status bar
  }
});
```

---

## Performans İpuçları

1. **`quality: 0.4`** — Kare kalitesini düşük tut. Yüksek kalite = büyük dosya = yavaş WebSocket
2. **`skipProcessing: true`** — iOS'ta görüntü işlemeyi atla, hız kazanır
3. **`SEND_FPS = 5`** — Saniyede 5 kare yeter. 30 kare göndermeye gerek yok
4. **`memo` / `useMemo`** — Hesaplamalı bileşenleri gereksiz yeniden çizimden koru
5. `FlatList` büyük listeler için `ScrollView`'den çok daha performanslı

---

## Sık Karşılaşılan Hatalar

**"Network request failed" hatası:**
- Sunucu IP'si yanlış giriliyor
- Telefon ve Mac aynı Wi-Fi'de değil
- Backend çalışmıyor (önce `./run_dev.sh` çalıştır)
- Güvenlik duvarı (firewall) 8000 portunu engelliyor olabilir

**"Camera permissions not granted":**
- iOS: Ayarlar → Uygulama → Kamera iznini aç
- Android: Ayarlar → Uygulamalar → İzinler → Kamera

**"Expo Go update required":**
- Expo SDK versiyonu Expo Go ile uyumsuz. `npm install expo@latest` ile güncelle

**Beyaz ekran / crash:**
- Terminal'e bak — orada hata mesajı var
- `r` tuşuna bas → Expo yeniden yükler
- `npx expo start --clear` → cache temizler

---

## İyileştirme Fikirleri

1. **Fotoğraf kaydetme** — Riskli olayda ekran görüntüsü al
2. **Bildirimleri** — CRITICAL seviye olay gelince bildirim gönder (`expo-notifications`)
3. **Harita** — Olayları haritada göster (`expo-location` + `react-native-maps`)
4. **Karanlık/Açık tema** — `useColorScheme` ile otomatik tema
5. **Çevrimdışı mod** — Bağlantı kesilince son sonuçları göster
6. **Gerçek navigation** — `react-navigation` kütüphanesiyle daha iyi ekran geçişleri

---

## Faydalı Kaynaklar

- [Expo Dökümantasyonu](https://docs.expo.dev/)
- [React Native Dökümantasyonu](https://reactnative.dev/docs/getting-started)
- [expo-camera API](https://docs.expo.dev/versions/latest/sdk/camera/)
- [TypeScript 5 Dakikada](https://www.typescriptlang.org/docs/handbook/typescript-in-5-minutes.html)
- [Flexbox Oyunu (öğrenmek için)](https://flexboxfroggy.com/)
