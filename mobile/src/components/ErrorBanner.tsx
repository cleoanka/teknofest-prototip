import React, { useEffect, useRef } from "react";
import { Animated, Text, TouchableOpacity, StyleSheet } from "react-native";
import { ApiErrorKind } from "../api/client";

interface Props {
  message: string;
  kind: ApiErrorKind;
  onDismiss: () => void;
}

const AUTO_DISMISS_MS = 4_000;

const KIND_COLOR: Record<ApiErrorKind, string> = {
  network: "#f5a623",  // turuncu — bağlantı yok
  timeout: "#f5a623",  // turuncu — zaman aşımı
  auth:    "#9b59b6",  // mor    — oturum hatası
  server:  "#ff4d5e",  // kırmızı — sunucu hatası
};

const KIND_ICON: Record<ApiErrorKind, string> = {
  network: "📡",
  timeout: "⏱",
  auth:    "🔒",
  server:  "⚠",
};

export default function ErrorBanner({ message, kind, onDismiss }: Props) {
  const translateY = useRef(new Animated.Value(-80)).current;

  useEffect(() => {
    // Yukarıdan aşağı kayarak gir
    Animated.spring(translateY, {
      toValue: 0,
      useNativeDriver: true,
      bounciness: 4,
    }).start();

    // N saniye sonra otomatik kapat
    const timer = setTimeout(() => slideOut(), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, []);

  const slideOut = () => {
    Animated.timing(translateY, {
      toValue: -80,
      duration: 250,
      useNativeDriver: true,
    }).start(onDismiss);
  };

  const color = KIND_COLOR[kind];
  const icon = KIND_ICON[kind];

  return (
    <Animated.View
      style={[s.banner, { borderLeftColor: color, transform: [{ translateY }] }]}
    >
      <Text style={s.icon}>{icon}</Text>
      <Text style={[s.message, { flex: 1 }]} numberOfLines={2}>{message}</Text>
      <TouchableOpacity onPress={slideOut} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
        <Text style={s.close}>✕</Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  banner: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "#1b2540",
    borderLeftWidth: 4,
    paddingHorizontal: 16,
    paddingVertical: 14,
    gap: 10,
    zIndex: 999,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
    elevation: 10,
  },
  icon: { fontSize: 18 },
  message: { color: "#e6ecff", fontSize: 13, lineHeight: 18 },
  close: { color: "#8a97bd", fontSize: 16, paddingLeft: 4 },
});
