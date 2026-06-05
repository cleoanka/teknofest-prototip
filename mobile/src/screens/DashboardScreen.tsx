import React, { useEffect, useRef, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Dimensions } from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { WS_INGEST } from "../api/client";
import { FrameResult } from "../types";

const SEND_FPS = 5;
const { width: SCREEN_W } = Dimensions.get("window");
const PREVIEW_H = Math.round((SCREEN_W * 9) / 16);

export default function DashboardScreen({ onOpenEvent, onLogout }:
  { onOpenEvent: (ev: any) => void; onLogout: () => void; }) {
  const [perm, requestPerm] = useCameraPermissions();
  const [facing, setFacing] = useState<"front" | "back">("back");
  const [result, setResult] = useState<FrameResult | null>(null);
  const [connected, setConnected] = useState(false);
  const camRef = useRef<CameraView>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const sentSize = useRef<{ w: number; h: number }>({ w: 640, h: 360 });

  useEffect(() => { if (!perm?.granted) requestPerm(); }, []);

  useEffect(() => {
    const ws = new WebSocket(WS_INGEST);
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (ev) => {
      try { const d = JSON.parse(ev.data); if (!d.error) setResult(d); } catch {}
    };
    const timer = setInterval(capture, 1000 / SEND_FPS);
    return () => { clearInterval(timer); ws.close(); };
  }, []);

  const capture = async () => {
    const ws = wsRef.current;
    if (!camRef.current || !ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      const pic = await camRef.current.takePictureAsync({ base64: true, quality: 0.4, skipProcessing: true });
      if (pic?.base64) {
        sentSize.current = { w: pic.width, h: pic.height };
        ws.send(JSON.stringify({ frame: "data:image/jpeg;base64," + pic.base64 }));
      }
    } catch {}
  };

  if (!perm?.granted) {
    return <View style={s.center}><Text style={s.dim}>Kamera izni gerekli…</Text>
      <TouchableOpacity style={s.smallBtn} onPress={requestPerm}><Text style={s.btnTxt}>İzin Ver</Text></TouchableOpacity></View>;
  }

  const crit = result?.mode === "CRITICAL";
  const scaleX = SCREEN_W / sentSize.current.w;
  const scaleY = PREVIEW_H / sentSize.current.h;

  return (
    <ScrollView style={s.root}>
      <View style={s.header}>
        <Text style={s.title}>Yol Güvenliği · Canlı</Text>
        <View style={s.row}>
          <View style={[s.dot, { backgroundColor: connected ? "#2ecc71" : "#ff4d5e" }]} />
          <Text style={s.dim}>{connected ? "Canlı" : "Bağlı değil"}</Text>
          <TouchableOpacity onPress={onLogout}><Text style={s.logout}>Çıkış</Text></TouchableOpacity>
        </View>
      </View>

      <View style={[s.preview, { height: PREVIEW_H }, crit && s.previewCrit]}>
        <CameraView ref={camRef} style={StyleSheet.absoluteFill} facing={facing} />
        {(result?.detections || []).map((d, i) => (
          <View key={i} style={[s.box, {
            left: d.bbox.x1 * scaleX, top: d.bbox.y1 * scaleY,
            width: (d.bbox.x2 - d.bbox.x1) * scaleX, height: (d.bbox.y2 - d.bbox.y1) * scaleY,
            borderColor: d.label === "vehicle" ? "#2f7bff" : d.label === "phone" ? "#ff4d5e" : "#2ecc71",
          }]}>
            <Text style={s.boxLabel}>{d.label} {(d.confidence * 100) | 0}%</Text>
          </View>
        ))}
        <View style={[s.badge, crit && s.badgeCrit]}>
          <Text style={s.badgeTxt}>{crit ? "● KRİTİK (QoD)" : "● NORMAL"}</Text>
        </View>
        <View style={s.hud}>
          <Text style={s.hudTxt}>Bant: {result?.qod.bandwidth_mbps ?? 5} Mbps</Text>
          <Text style={s.hudTxt}>{crit ? "1080p" : "480p"}</Text>
          <Text style={s.hudTxt}>FPS: {result?.fps ?? 0}</Text>
        </View>
      </View>

      <View style={s.controls}>
        <TouchableOpacity style={s.smallBtn} onPress={() => setFacing(f => f === "back" ? "front" : "back")}>
          <Text style={s.btnTxt}>Kamera Çevir</Text>
        </TouchableOpacity>
      </View>

      {/* Araç & Plaka */}
      <View style={s.card}>
        <Text style={s.cardTitle}>ARAÇ & PLAKA</Text>
        <View style={s.grid}>
          <Metric label="Plaka" value={result?.vehicle.plate.text || "—"} />
          <Metric label="Hız" value={result?.vehicle.speed_kmh != null ? result.vehicle.speed_kmh + " km/h" : "—"} />
          <Metric label="Tip" value={result?.vehicle.vtype || "—"} />
          <Metric label="Renk" value={result?.vehicle.color || "—"} />
        </View>
      </View>

      {/* Risk */}
      <View style={s.card}>
        <Text style={s.cardTitle}>SÜRÜCÜ RİSKİ</Text>
        <View style={s.row}>
          <Text style={s.bigScore}>{result?.risk.score ?? 0}</Text>
          <Text style={[s.lvl, lvlStyle(result?.risk.level)]}>{result?.risk.level || "LOW"}</Text>
        </View>
        <View style={s.barBg}>
          <View style={[s.barFill, { width: `${result?.risk.score ?? 0}%`, backgroundColor: riskColor(result?.risk.score ?? 0) }]} />
        </View>
        <View style={s.tags}>
          {(result?.risk.factors || []).map((f, i) => <Text key={i} style={s.tag}>{f}</Text>)}
        </View>
      </View>

      <View style={s.card}>
        <Text style={s.cardTitle}>QoD TETİK</Text>
        <Text style={s.dim}>Sebep: {result?.qod.last_trigger_reason || "—"}</Text>
        <Text style={s.dim}>Oturum yaşı: {result?.qod.session_age_s ?? 0}s</Text>
      </View>
    </ScrollView>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <View style={s.metric}><Text style={s.metricLabel}>{label}</Text><Text style={s.metricVal}>{value}</Text></View>;
}
function riskColor(s: number) { return s >= 85 ? "#ff4d5e" : s >= 60 ? "#ff8a50" : s >= 30 ? "#f5a623" : "#2ecc71"; }
function lvlStyle(l?: string) { return { color: riskColor(l === "CRITICAL" ? 90 : l === "HIGH" ? 70 : l === "MEDIUM" ? 40 : 0) }; }

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b1020" },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 16 },
  title: { color: "#e6ecff", fontSize: 18, fontWeight: "700" },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  dim: { color: "#8a97bd", fontSize: 13 },
  logout: { color: "#ff4d5e", marginLeft: 10, fontSize: 13 },
  preview: { marginHorizontal: 16, borderRadius: 14, overflow: "hidden", backgroundColor: "#000" },
  previewCrit: { borderWidth: 2, borderColor: "#ff4d5e" },
  box: { position: "absolute", borderWidth: 2, borderRadius: 4 },
  boxLabel: { color: "#fff", fontSize: 10, backgroundColor: "rgba(0,0,0,.6)", paddingHorizontal: 3 },
  badge: { position: "absolute", top: 10, left: 10, backgroundColor: "rgba(46,204,113,.2)", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8 },
  badgeCrit: { backgroundColor: "rgba(255,77,94,.25)" },
  badgeTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  hud: { position: "absolute", bottom: 10, left: 10, flexDirection: "row", gap: 12 },
  hudTxt: { color: "#fff", fontSize: 11, backgroundColor: "rgba(11,16,32,.7)", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  controls: { flexDirection: "row", padding: 16, gap: 10 },
  smallBtn: { backgroundColor: "#1b2540", paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10, marginTop: 10 },
  btnTxt: { color: "#e6ecff", fontWeight: "600" },
  card: { backgroundColor: "#131a2e", marginHorizontal: 16, marginBottom: 14, borderRadius: 14, padding: 16, borderWidth: 1, borderColor: "#25304f" },
  cardTitle: { color: "#8a97bd", fontSize: 11, letterSpacing: 1, marginBottom: 12 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  metric: { width: "47%", backgroundColor: "#1b2540", padding: 12, borderRadius: 10 },
  metricLabel: { color: "#8a97bd", fontSize: 11 },
  metricVal: { color: "#e6ecff", fontSize: 16, fontWeight: "700", marginTop: 4 },
  bigScore: { color: "#e6ecff", fontSize: 30, fontWeight: "800" },
  lvl: { fontWeight: "700", fontSize: 14 },
  barBg: { height: 10, backgroundColor: "#1b2540", borderRadius: 999, marginVertical: 10, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999 },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  tag: { color: "#f5a623", fontSize: 11, backgroundColor: "rgba(245,166,35,.15)", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
});
