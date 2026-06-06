import React, { useCallback, useState } from "react";
import { StatusBar } from "expo-status-bar";
import { SafeAreaView, StyleSheet, View } from "react-native";
import LoginScreen from "./src/screens/LoginScreen";
import DashboardScreen from "./src/screens/DashboardScreen";
import EventListScreen from "./src/screens/EventListScreen";
import EventDetailScreen from "./src/screens/EventDetailScreen";
import ErrorBanner from "./src/components/ErrorBanner";
import { ApiError, ApiErrorKind } from "./src/api/client";
import { MOCK_MODE } from "./src/config";
import { StoredEvent } from "./src/types";

export type Screen = "login" | "dashboard" | "eventlist" | "detail";

interface AppError { message: string; kind: ApiErrorKind; }

export default function App() {
  // Mock modda login'i atla, direkt dashboard'dan başla
  const [screen, setScreen] = useState<Screen>(MOCK_MODE ? "dashboard" : "login");
  const [token, setToken] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<StoredEvent | null>(null);
  const [detailSource, setDetailSource] = useState<"dashboard" | "eventlist">("dashboard");
  const [appError, setAppError] = useState<AppError | null>(null);

  // Herhangi bir ekrandan fırlatılan hatayı yakala
  const handleError = useCallback((e: unknown) => {
    if (e instanceof ApiError) {
      setAppError({ message: e.message, kind: e.kind });
      // Oturum hatası → login'e at
      if (e.kind === "auth") {
        setToken(null);
        setScreen("login");
      }
    } else if (e instanceof Error) {
      setAppError({ message: e.message, kind: "server" });
    }
  }, []);

  const openEvent = (ev: StoredEvent, source: "dashboard" | "eventlist" = "eventlist") => {
    setSelectedEvent(ev);
    setDetailSource(source);
    setScreen("detail");
  };

  return (
    <SafeAreaView style={styles.root}>
      <StatusBar style="light" />

      {screen === "login" && (
        <LoginScreen
          onSuccess={(t) => { setToken(t); setScreen("dashboard"); }}
        />
      )}

      {screen === "dashboard" && (
        <DashboardScreen
          onOpenEvent={(ev) => openEvent(ev, "dashboard")}
          onOpenHistory={() => setScreen("eventlist")}
          onLogout={() => { setToken(null); setScreen("login"); }}
        />
      )}

      {screen === "eventlist" && (
        <EventListScreen
          onOpenEvent={(ev) => openEvent(ev, "eventlist")}
          onBack={() => setScreen("dashboard")}
          onError={handleError}
        />
      )}

      {screen === "detail" && (
        <EventDetailScreen
          event={selectedEvent}
          onBack={() => setScreen(detailSource)}
        />
      )}

      {/* Global hata banner'ı — tüm ekranların üstünde görünür */}
      {appError && (
        <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
          <ErrorBanner
            message={appError.message}
            kind={appError.kind}
            onDismiss={() => setAppError(null)}
          />
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b1020" },
});
