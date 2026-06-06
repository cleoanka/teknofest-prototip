import React, { useEffect, useRef } from "react";
import { Animated, Text, TouchableOpacity, StyleSheet } from "react-native";
import { colors, spacing, radius, font } from "../theme";
import type { ApiErrorKind } from "../api/client";

const KIND_COLOR: Record<string, string> = {
  network: colors.warn,
  timeout: colors.warn,
  auth: colors.purple,
  server: colors.danger,
  parse: colors.danger,
};
const KIND_ICON: Record<string, string> = {
  network: "📡", timeout: "⏱", auth: "🔒", server: "⚠", parse: "⚠",
};

/** Ekranın altından kayarak gelen, otomatik kapanan hata bandı. */
export function ErrorBanner({ message, kind = "server", onDismiss }: {
  message: string; kind?: ApiErrorKind; onDismiss: () => void;
}) {
  const y = useRef(new Animated.Value(120)).current;
  const color = KIND_COLOR[kind] ?? colors.danger;

  useEffect(() => {
    Animated.spring(y, { toValue: 0, useNativeDriver: true, bounciness: 5 }).start();
    const t = setTimeout(close, 4000);
    return () => clearTimeout(t);
  }, []);

  const close = () => {
    Animated.timing(y, { toValue: 120, duration: 220, useNativeDriver: true }).start(onDismiss);
  };

  return (
    <Animated.View style={[s.wrap, { borderColor: color + "55", transform: [{ translateY: y }] }]}>
      <Text style={s.icon}>{KIND_ICON[kind] ?? "⚠"}</Text>
      <Text style={[s.msg, { color }]} numberOfLines={2}>{message}</Text>
      <TouchableOpacity onPress={close} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
        <Text style={[s.close, { color }]}>✕</Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

const s = StyleSheet.create({
  wrap: {
    position: "absolute", left: spacing.lg, right: spacing.lg, bottom: spacing.xl,
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.cardElev, borderWidth: 1, borderRadius: radius.lg,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    shadowColor: "#000", shadowOpacity: 0.4, shadowRadius: 10, shadowOffset: { width: 0, height: 4 },
    elevation: 10,
  },
  icon: { fontSize: 18 },
  msg: { flex: 1, fontSize: font.small, fontWeight: font.medium, lineHeight: 19 },
  close: { fontSize: 16, fontWeight: font.semibold },
});
