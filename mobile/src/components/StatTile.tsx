import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { colors, spacing, radius, font } from "../theme";

/** Etiket + büyük değer + alt açıklama içeren istatistik kutusu. */
export function StatTile({ label, value, sub, accent = colors.text, width }: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
  width?: any;
}) {
  return (
    <View style={[s.tile, width != null && { width }]}>
      <Text style={s.label}>{label}</Text>
      <Text style={[s.value, { color: accent }]} numberOfLines={1} adjustsFontSizeToFit>
        {value}
      </Text>
      {sub ? <Text style={s.sub}>{sub}</Text> : null}
    </View>
  );
}

const s = StyleSheet.create({
  tile: {
    backgroundColor: colors.bgElev,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.borderSoft,
  },
  label: { color: colors.textMuted, fontSize: font.tiny, letterSpacing: 0.5, marginBottom: 6 },
  value: { fontSize: font.h2, fontWeight: font.bold },
  sub: { color: colors.textDim, fontSize: font.tiny, marginTop: 4 },
});
