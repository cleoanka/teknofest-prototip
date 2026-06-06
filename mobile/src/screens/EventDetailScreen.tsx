import React from "react";
import {
  View, Text, TouchableOpacity, StyleSheet, ScrollView,
} from "react-native";
import { StoredEvent } from "../types";

interface Props {
  event: StoredEvent | null;
  onBack: () => void;
}

export default function EventDetailScreen({ event, onBack }: Props) {
  if (!event) {
    return (
      <View style={s.center}>
        <Text style={s.dim}>Olay bulunamadı.</Text>
        <TouchableOpacity style={s.backBtn} onPress={onBack}>
          <Text style={s.back}>‹ Geri</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const color = riskColor(event.risk_score);
  const date = new Date(event.ts * 1000).toLocaleString("tr-TR");
  const factors = event.factors
    ? event.factors.split(",").map((f) => f.trim()).filter(Boolean)
    : [];

  return (
    <ScrollView style={s.root}>
      <View style={s.header}>
        <TouchableOpacity onPress={onBack}>
          <Text style={s.back}>‹ Geri</Text>
        </TouchableOpacity>
        <Text style={s.title}>Olay Detayı</Text>
        <View style={{ width: 50 }} />
      </View>

      <View style={s.plateCard}>
        <Text style={s.plateLabel}>PLAKA</Text>
        <Text style={s.plate}>{event.plate || "—"}</Text>
        <View style={[s.badge, { backgroundColor: color + "22", borderColor: color + "66" }]}>
          <Text style={[s.badgeTxt, { color }]}>
            {event.risk_level} · {event.risk_score}
          </Text>
        </View>
      </View>

      <View style={s.barBg}>
        <View style={[s.barFill, { width: `${event.risk_score}%`, backgroundColor: color }]} />
      </View>

      <View style={s.card}>
        <Text style={s.cardTitle}>ARAÇ BİLGİSİ</Text>
        <Row label="Tip" value={event.vtype || "—"} />
        <Row label="Hız" value={event.speed_kmh != null ? `${event.speed_kmh} km/h` : "—"} />
        <Row label="Mod" value={event.mode} />
        <Row label="Tarih" value={date} />
      </View>

      {factors.length > 0 && (
        <View style={s.card}>
          <Text style={s.cardTitle}>RİSK FAKTÖRLERİ</Text>
          <View style={s.tags}>
            {factors.map((f, i) => (
              <Text key={i} style={s.tag}>{f}</Text>
            ))}
          </View>
        </View>
      )}
    </ScrollView>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={s.row}>
      <Text style={s.rowLabel}>{label}</Text>
      <Text style={s.rowValue}>{value}</Text>
    </View>
  );
}

function riskColor(score: number) {
  return score >= 85 ? "#ff4d5e" : score >= 60 ? "#ff8a50" : score >= 30 ? "#f5a623" : "#2ecc71";
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b1020" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: 16, borderBottomWidth: 1, borderBottomColor: "#1b2540",
  },
  back: { color: "#2f7bff", fontSize: 16, minWidth: 50 },
  title: { color: "#e6ecff", fontSize: 18, fontWeight: "700" },
  plateCard: { alignItems: "center", paddingVertical: 28, paddingHorizontal: 16 },
  plateLabel: { color: "#8a97bd", fontSize: 11, letterSpacing: 1, marginBottom: 8 },
  plate: { color: "#e6ecff", fontSize: 36, fontWeight: "900", letterSpacing: 4, marginBottom: 12 },
  badge: {
    paddingHorizontal: 16, paddingVertical: 6,
    borderRadius: 999, borderWidth: 1,
  },
  badgeTxt: { fontSize: 14, fontWeight: "700" },
  barBg: { height: 8, backgroundColor: "#1b2540", marginHorizontal: 16, borderRadius: 999, overflow: "hidden", marginBottom: 16 },
  barFill: { height: "100%", borderRadius: 999 },
  card: {
    backgroundColor: "#131a2e", marginHorizontal: 16, marginBottom: 14,
    borderRadius: 14, padding: 16, borderWidth: 1, borderColor: "#25304f",
  },
  cardTitle: { color: "#8a97bd", fontSize: 11, letterSpacing: 1, marginBottom: 12 },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: "#1b2540" },
  rowLabel: { color: "#8a97bd", fontSize: 14 },
  rowValue: { color: "#e6ecff", fontSize: 14, fontWeight: "600" },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  tag: {
    color: "#f5a623", fontSize: 12, fontWeight: "600",
    backgroundColor: "rgba(245,166,35,.15)", paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999,
  },
  backBtn: { marginTop: 20, padding: 12 },
  dim: { color: "#8a97bd", fontSize: 14 },
});
