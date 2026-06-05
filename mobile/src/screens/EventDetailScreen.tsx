import React from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";

export default function EventDetailScreen({ event, onBack }: { event: any; onBack: () => void }) {
  return (
    <View style={s.root}>
      <TouchableOpacity onPress={onBack}><Text style={s.back}>‹ Geri</Text></TouchableOpacity>
      <Text style={s.title}>Olay Detayı</Text>
      {event ? (
        <View style={s.card}>
          <Row k="Plaka" v={event.plate || "—"} />
          <Row k="Araç tipi" v={event.vtype || "—"} />
          <Row k="Hız" v={event.speed_kmh ? event.speed_kmh + " km/h" : "—"} />
          <Row k="Risk skoru" v={String(event.risk_score)} />
          <Row k="Seviye" v={event.risk_level} />
          <Row k="Etkenler" v={(event.factors || "").replaceAll(",", ", ")} />
          <Row k="Mod" v={event.mode} />
          <Row k="Zaman" v={new Date(event.ts * 1000).toLocaleString("tr-TR")} />
        </View>
      ) : <Text style={s.dim}>Olay bulunamadı.</Text>}
    </View>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <View style={s.row}><Text style={s.k}>{k}</Text><Text style={s.v}>{v}</Text></View>;
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b1020", padding: 16 },
  back: { color: "#2f7bff", fontSize: 16, marginBottom: 10 },
  title: { color: "#e6ecff", fontSize: 22, fontWeight: "800", marginBottom: 16 },
  card: { backgroundColor: "#131a2e", borderRadius: 14, padding: 16, borderWidth: 1, borderColor: "#25304f" },
  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#25304f" },
  k: { color: "#8a97bd" }, v: { color: "#e6ecff", fontWeight: "600" },
  dim: { color: "#8a97bd" },
});
