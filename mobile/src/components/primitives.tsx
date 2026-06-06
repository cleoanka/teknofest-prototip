import React from "react";
import { View, Text, StyleSheet, ViewStyle, StyleProp } from "react-native";
import { colors, spacing, radius, font } from "../theme";

/** Standart içerik kartı. */
export function Card({ children, style }: { children: React.ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.card, style]}>{children}</View>;
}

/** Kart üstü küçük büyük-harf başlık. */
export function CardTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <View style={s.titleRow}>
      <Text style={s.title}>{children}</Text>
      {right}
    </View>
  );
}

/** Küçük etiket (chip). */
export function Pill({ label, color = colors.textDim, bg }: { label: string; color?: string; bg?: string }) {
  return (
    <View style={[s.pill, { backgroundColor: bg ?? color + "22", borderColor: color + "55" }]}>
      <Text style={[s.pillTxt, { color }]}>{label}</Text>
    </View>
  );
}

/** Bağlantı / durum noktası. */
export function StatusDot({ color }: { color: string }) {
  return <View style={[s.dot, { backgroundColor: color }]} />;
}

/** İnce ayraç. */
export function Divider() {
  return <View style={s.divider} />;
}

/** Boş durum göstergesi. */
export function EmptyState({ icon = "—", text }: { icon?: string; text: string }) {
  return (
    <View style={s.empty}>
      <Text style={s.emptyIcon}>{icon}</Text>
      <Text style={s.emptyTxt}>{text}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.md },
  title: { color: colors.textDim, fontSize: font.tiny, letterSpacing: 1.2, fontWeight: font.semibold },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, borderWidth: 1 },
  pillTxt: { fontSize: font.tiny, fontWeight: font.semibold },
  dot: { width: 9, height: 9, borderRadius: 5 },
  divider: { height: 1, backgroundColor: colors.borderSoft, marginVertical: spacing.md },
  empty: { alignItems: "center", justifyContent: "center", paddingVertical: spacing.xxl },
  emptyIcon: { fontSize: 36, marginBottom: spacing.sm },
  emptyTxt: { color: colors.textMuted, fontSize: font.body, textAlign: "center" },
});
