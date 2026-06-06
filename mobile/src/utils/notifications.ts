import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

// Uygulama ön plandayken bildirimlerin nasıl gösterileceğini tanımla
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,  // SDK 54: shouldShowAlert yerine geldi
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

const CHANNEL_ID = "critical-alerts";
const COOLDOWN_MS = 30_000;

let _lastFiredAt = 0;
let _permGranted = false;

export async function setupNotifications(): Promise<boolean> {
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync(CHANNEL_ID, {
      name: "Kritik Uyarılar",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 300, 200, 300],
      lightColor: "#FF4D5E",
      sound: "default",
    });
  }

  const { status } = await Notifications.requestPermissionsAsync({
    ios: { allowAlert: true, allowBadge: false, allowSound: true },
  });
  _permGranted = status === "granted";
  return _permGranted;
}

export async function fireCriticalNotification(
  plate: string | null,
  score: number,
): Promise<void> {
  if (!_permGranted) return;

  const now = Date.now();
  if (now - _lastFiredAt < COOLDOWN_MS) return; // 30s spam önlemi
  _lastFiredAt = now;

  await Notifications.scheduleNotificationAsync({
    content: {
      title: "Kritik Risk Tespit Edildi!",
      body: `Plaka: ${plate || "Bilinmiyor"} — Skor: ${score}`,
      sound: "default",
      data: { plate, score },
      ...(Platform.OS === "android" && { channelId: CHANNEL_ID }),
    },
    trigger: null, // Hemen gönder
  });
}
