import React from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { colors, spacing, radius, font, riskColor } from "../../theme";
import { Card, CardTitle, Pill, Divider } from "../../components/primitives";
import { ProgressBar } from "../../components/ProgressBar";
import type { EventRecord } from "../../types/api";

export default function EventDetailScreen({ route }: any) {
  const event: EventRecord | undefined = route?.params?.event;

  if (!event) {
    return <View style={s.center}><Text style={s.dim}>Olay bulunamadı.</Text></View>;
  }

  const color = riskColor(event.risk_score);
  const factors = (event.factors || "").split(",").map(f => f.trim()).filter(Boolean);

  return (
    <ScrollView style={s.root} contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.xxl }}>
      {/* Plaka kahramanı */}
      <View style={s.hero}>
        <Text style={s.heroLabel}>PLAKA</Text>
        <Text style={s.plate}>{event.plate || "—"}</Text>
        <View style={[s.heroBadge, { backgroundColor: color + "22", borderColor: color + "66" }]}>
          <Text style={[s.heroBadgeTxt, { color }]}>{event.risk_level} · {event.risk_score}/100</Text>
        </View>
      </View>

      <Card>
        <CardTitle>RİSK SKORU</CardTitle>
        <ProgressBar value={event.risk_score} color={color} height={12} />
      </Card>

      <Card style={{ marginTop: spacing.md }}>
        <CardTitle>ARAÇ BİLGİSİ</CardTitle>
        <Row k="Araç tipi" v={event.vtype || "—"} />
        <Divider />
        <Row k="Hız" v={event.speed_kmh != null ? `${Math.round(event.speed_kmh)} km/h` : "—"} />
        <Divider />
        <Row k="Mod" v={event.mode} />
        <Divider />
        <Row k="Zaman" v={new Date(event.ts * 1000).toLocaleString("tr-TR")} />
      </Card>

      {factors.length > 0 && (
        <Card style={{ marginTop: spacing.md }}>
          <CardTitle>RİSK FAKTÖRLERİ</CardTitle>
          <View style={s.factors}>
            {factors.map((f, i) => <Pill key={i} label={f} color={colors.warn} />)}
          </View>
        </Card>
      )}
    </ScrollView>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <View style={s.row}>
      <Text style={s.k}>{k}</Text>
      <Text style={s.v}>{v}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, backgroundColor: colors.bg, alignItems: "center", justifyContent: "center" },
  dim: { color: colors.textDim },
  hero: { alignItems: "center", paddingVertical: spacing.xl },
  heroLabel: { color: colors.textMuted, fontSize: font.tiny, letterSpacing: 1.5, marginBottom: spacing.sm },
  plate: { color: colors.text, fontSize: 38, fontWeight: font.bold, letterSpacing: 4, marginBottom: spacing.md },
  heroBadge: { paddingHorizontal: spacing.lg, paddingVertical: 6, borderRadius: radius.pill, borderWidth: 1 },
  heroBadgeTxt: { fontSize: font.small, fontWeight: font.bold },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", paddingVertical: spacing.sm },
  k: { color: colors.textDim, fontSize: font.body },
  v: { color: colors.text, fontSize: font.body, fontWeight: font.medium },
  factors: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
});
