import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { riskColor, riskColorByLevel, font, radius } from "../theme";

/** Risk seviyesi + skor rozeti. */
export function RiskBadge({ level, score, size = "md" }: {
  level: string; score?: number; size?: "sm" | "md";
}) {
  const color = score != null ? riskColor(score) : riskColorByLevel(level);
  const small = size === "sm";
  return (
    <View style={[
      s.badge,
      { backgroundColor: color + "22", borderColor: color + "66" },
      small ? s.sm : s.md,
    ]}>
      <Text style={[s.txt, { color, fontSize: small ? font.tiny : font.small }]}>
        {level}{score != null ? ` · ${score}` : ""}
      </Text>
    </View>
  );
}

const s = StyleSheet.create({
  badge: { borderRadius: radius.pill, borderWidth: 1, alignSelf: "flex-start" },
  sm: { paddingHorizontal: 8, paddingVertical: 3 },
  md: { paddingHorizontal: 12, paddingVertical: 5 },
  txt: { fontWeight: font.semibold },
});
