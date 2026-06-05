import React, { useState } from "react";
import { StatusBar } from "expo-status-bar";
import { SafeAreaView, StyleSheet } from "react-native";
import LoginScreen from "./src/screens/LoginScreen";
import DashboardScreen from "./src/screens/DashboardScreen";
import EventDetailScreen from "./src/screens/EventDetailScreen";

export type Screen = "login" | "dashboard" | "detail";

export default function App() {
  const [screen, setScreen] = useState<Screen>("login");
  const [token, setToken] = useState<string | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<any>(null);

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

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b1020" },
});
