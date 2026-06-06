import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated, View, Text, TouchableOpacity,
  StyleSheet, ScrollView, Dimensions,
} from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useWebSocket, WsStatus } from "../hooks/useWebSocket";
import PermissionDenied from "../components/PermissionDenied";
import { setupNotifications, fireCriticalNotification } from "../utils/notifications";
import { colors, riskColor, riskColorByLevel } from "../theme";
import { MOCK_MODE } from "../config";
import { MOCK_FRAMES } from "../mocks/frameResult";
import { FrameResult } from "../types";

const SEND_FPS = 5;
const { width: SCREEN_W } = Dimensions.get("window");
const PREVIEW_H = Math.round((SCREEN_W * 9) / 16);

export default function DashboardScreen({ onOpenEvent, onOpenHistory, onLogout }: {
  onOpenEvent: (ev: any) => void;
  onOpenHistory: () => void;
  onLogout: () => void;
}) {
  const [perm, requestPerm] = useCameraPermissions();
  const [facing, setFacing] = useState<"front" | "back">("back");
  const [result, setResult] = useState<FrameResult | null>(null);
  const [displayScore, setDisplayScore] = useState(0);
  const camRef = useRef<CameraView>(null);
  const sentSize = useRef<{ w: number; h: number }>({ w: 640, h: 360 });

  // ── Animasyonlar ──────────────────────────────────────────────────────────
  const scoreAnim = useRef(new Animated.Value(0)).current;
  const critBorder = useRef(new Animated.Value(0)).current;
  const critLoopRef = useRef<Animated.CompositeAnimation | null>(null);

  const crit = result?.mode === "CRITICAL";

  // Risk skoru çubuğu + sayaç animasyonu
  useEffect(() => {
    const target = result?.risk.score ?? 0;
    const listenerId = scoreAnim.addListener(({ value }) => setDisplayScore(Math.round(value)));

    Animated.timing(scoreAnim, {
      toValue: target,
      duration: 450,
      useNativeDriver: false,
    }).start(() => {
      scoreAnim.removeListener(listenerId);
      setDisplayScore(target); // tam değeri garantile
    });

    return () => scoreAnim.removeListener(listenerId);
  }, [result?.risk.score]);

  // QoD CRITICAL modda kamera çerçevesi pulse animasyonu
  useEffect(() => {
    critLoopRef.current?.stop();
    critLoopRef.current = null;

    if (crit) {
      critLoopRef.current = Animated.loop(
        Animated.sequence([
          Animated.timing(critBorder, { toValue: 1,    duration: 600, useNativeDriver: false }),
          Animated.timing(critBorder, { toValue: 0.25, duration: 600, useNativeDriver: false }),
        ]),
      );
      critLoopRef.current.start();
    } else {
      Animated.timing(critBorder, { toValue: 0, duration: 300, useNativeDriver: false }).start();
    }

    return () => { critLoopRef.current?.stop(); };
  }, [crit]);

  const animBarWidth = scoreAnim.interpolate({
    inputRange: [0, 100],
    outputRange: ["0%", "100%"],
  });

  const animBorderColor = critBorder.interpolate({
    inputRange: [0, 0.25, 1],
    outputRange: [
      "rgba(255,77,94,0)",
      "rgba(255,77,94,0.3)",
      "rgba(255,77,94,1)",
    ],
  });

  // ── Hooks ─────────────────────────────────────────────────────────────────
  const handleMessage = useCallback((data: FrameResult) => {
    setResult(data);
    if (data.risk.level === "CRITICAL") {
      fireCriticalNotification(data.vehicle.plate.text, data.risk.score);
    }
  }, []);

  const { status, send } = useWebSocket({ onMessage: handleMessage, disabled: MOCK_MODE });

  useEffect(() => {
    if (perm && !perm.granted && perm.canAskAgain) requestPerm();
  }, [perm?.status]);

  useEffect(() => { setupNotifications(); }, []);

  // Gerçek kamera döngüsü — mock modda çalışmaz
  useEffect(() => {
    if (MOCK_MODE) return;
    const timer = setInterval(capture, 1000 / SEND_FPS);
    return () => clearInterval(timer);
  }, []);

  // Mock veri döngüsü — 2 saniyede bir sonraki senaryoya geçer
  useEffect(() => {
    if (!MOCK_MODE) return;
    let idx = 0;
    const timer = setInterval(() => {
      const frame = { ...MOCK_FRAMES[idx % MOCK_FRAMES.length], ts: Date.now() / 1000 };
      handleMessage(frame as FrameResult);
      idx++;
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  const capture = async () => {
    if (!camRef.current) return;
    try {
      const pic = await camRef.current.takePictureAsync({
        base64: true, quality: 0.4, skipProcessing: true,
      });
      if (pic?.base64) {
        sentSize.current = { w: pic.width, h: pic.height };
        send(JSON.stringify({ frame: "data:image/jpeg;base64," + pic.base64 }));
      }
    } catch {}
  };

  // ── İzin kontrolleri ──────────────────────────────────────────────────────
  if (!perm) {
    return (
      <View style={s.center}>
        <Text style={s.dim}>Kamera izni kontrol ediliyor…</Text>
      </View>
    );
  }

  if (!perm.granted) {
    return <PermissionDenied permanent={!perm.canAskAgain} onRequestAgain={requestPerm} />;
  }

  // ── Render ────────────────────────────────────────────────────────────────
  const scaleX = SCREEN_W / sentSize.current.w;
  const scaleY = PREVIEW_H / sentSize.current.h;
  const barColor = riskColor(result?.risk.score ?? 0);

  return (
    <ScrollView style={s.root}>
      <View style={s.header}>
        <Text style={s.title}>Yol Güvenliği · Canlı</Text>
        <View style={s.row}>
          <View style={[s.dot, { backgroundColor: wsStatusColor(status) }]} />
          <Text style={s.dim}>{wsStatusLabel(status)}</Text>
          <TouchableOpacity onPress={onLogout}>
            <Text style={s.logout}>Çıkış</Text>
          </TouchableOpacity>
        </View>
      </View>

      {MOCK_MODE && (
        <View style={s.mockBanner}>
          <Text style={s.mockBannerTxt}>🧪 MOCK MOD — Sahte veri döngüsü aktif</Text>
        </View>
      )}

      {!MOCK_MODE && (status === "reconnecting" || status === "disconnected") && (
        <View style={[s.reconnectBanner, status === "reconnecting" && s.reconnectingBg]}>
          <Text style={s.reconnectTxt}>
            {status === "reconnecting" ? "⟳ Yeniden bağlanıyor…" : "✕ Bağlantı kesildi"}
          </Text>
        </View>
      )}

      {/* Kamera önizleme — QoD pulse sınır animasyonu */}
      <Animated.View style={[s.previewWrapper, { borderColor: animBorderColor }]}>
        <View style={[s.preview, { height: PREVIEW_H }]}>
          <CameraView ref={camRef} style={StyleSheet.absoluteFill} facing={facing} />

          {(result?.detections || []).map((d, i) => (
            <View key={i} style={[s.box, {
              left:   d.bbox.x1 * scaleX,
              top:    d.bbox.y1 * scaleY,
              width:  (d.bbox.x2 - d.bbox.x1) * scaleX,
              height: (d.bbox.y2 - d.bbox.y1) * scaleY,
              borderColor: d.label === "vehicle" ? colors.accent
                         : d.label === "phone"   ? colors.danger
                         : colors.riskLow,
            }]}>
              <Text style={s.boxLabel}>{d.label} {(d.confidence * 100) | 0}%</Text>
            </View>
          ))}

          <View style={[s.modeBadge, crit && s.modeBadgeCrit]}>
            <Text style={s.modeBadgeTxt}>{crit ? "● KRİTİK (QoD)" : "● NORMAL"}</Text>
          </View>

          <View style={s.hud}>
            <Text style={s.hudTxt}>Bant: {result?.qod.bandwidth_mbps ?? 5} Mbps</Text>
            <Text style={s.hudTxt}>{crit ? "1080p" : "480p"}</Text>
            <Text style={s.hudTxt}>FPS: {result?.fps ?? 0}</Text>
          </View>
        </View>
      </Animated.View>

      <View style={s.controls}>
        <TouchableOpacity style={s.smallBtn}
          onPress={() => setFacing(f => f === "back" ? "front" : "back")}>
          <Text style={s.btnTxt}>Kamera Çevir</Text>
        </TouchableOpacity>
        <TouchableOpacity style={[s.smallBtn, s.historyBtn]} onPress={onOpenHistory}>
          <Text style={s.btnTxt}>📋 Geçmiş</Text>
        </TouchableOpacity>
      </View>

      {/* Araç & Plaka */}
      <View style={s.card}>
        <Text style={s.cardTitle}>ARAÇ & PLAKA</Text>
        <View style={s.grid}>
          <Metric label="Plaka" value={result?.vehicle.plate.text || "—"} />
          <Metric label="Hız"   value={result?.vehicle.speed_kmh != null ? result.vehicle.speed_kmh + " km/h" : "—"} />
          <Metric label="Tip"   value={result?.vehicle.vtype || "—"} />
          <Metric label="Renk"  value={result?.vehicle.color || "—"} />
        </View>
      </View>

      {/* Sürücü riski — animasyonlu çubuk */}
      <View style={s.card}>
        <Text style={s.cardTitle}>SÜRÜCÜ RİSKİ</Text>
        <View style={s.row}>
          <Text style={s.bigScore}>{displayScore}</Text>
          <Text style={[s.lvl, { color: riskColorByLevel(result?.risk.level) }]}>
            {result?.risk.level || "LOW"}
          </Text>
        </View>
        <View style={s.barBg}>
          <Animated.View style={[s.barFill, { width: animBarWidth, backgroundColor: barColor }]} />
        </View>
        <View style={s.tags}>
          {(result?.risk.factors || []).map((f, i) => (
            <Text key={i} style={s.tag}>{f}</Text>
          ))}
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
  return (
    <View style={s.metric}>
      <Text style={s.metricLabel}>{label}</Text>
      <Text style={s.metricVal}>{value}</Text>
    </View>
  );
}

function wsStatusColor(status: WsStatus): string {
  switch (status) {
    case "connected":    return colors.riskLow;
    case "reconnecting": return colors.riskMedium;
    case "connecting":   return colors.textSecondary;
    case "disconnected": return colors.danger;
  }
}

function wsStatusLabel(status: WsStatus): string {
  switch (status) {
    case "connected":    return "Canlı";
    case "reconnecting": return "Yeniden bağlanıyor…";
    case "connecting":   return "Bağlanıyor…";
    case "disconnected": return "Bağlı değil";
  }
}

const s = StyleSheet.create({
  root:    { flex: 1, backgroundColor: colors.bg },
  center:  { flex: 1, alignItems: "center", justifyContent: "center" },
  header:  { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: 16 },
  title:   { color: colors.textPrimary, fontSize: 18, fontWeight: "700" },
  row:     { flexDirection: "row", alignItems: "center", gap: 8 },
  dot:     { width: 8, height: 8, borderRadius: 4 },
  dim:     { color: colors.textSecondary, fontSize: 13 },
  logout:  { color: colors.danger, marginLeft: 10, fontSize: 13 },

  mockBanner:    { marginHorizontal: 16, marginBottom: 8, padding: 10, borderRadius: 10, backgroundColor: "rgba(46,204,113,.12)", alignItems: "center", borderWidth: 1, borderColor: "rgba(46,204,113,.3)" },
  mockBannerTxt: { color: colors.riskLow, fontSize: 12, fontWeight: "700" },

  reconnectBanner:  { marginHorizontal: 16, marginBottom: 8, padding: 10, borderRadius: 10, backgroundColor: "rgba(255,77,94,.15)", alignItems: "center" },
  reconnectingBg:   { backgroundColor: "rgba(245,166,35,.15)" },
  reconnectTxt:     { color: colors.textPrimary, fontSize: 13, fontWeight: "600" },

  // Dış animasyonlu sınır, iç kırpma kutusu
  previewWrapper: { marginHorizontal: 16, borderRadius: 14, borderWidth: 2 },
  preview:        { borderRadius: 12, overflow: "hidden", backgroundColor: "#000" },

  box:      { position: "absolute", borderWidth: 2, borderRadius: 4 },
  boxLabel: { color: "#fff", fontSize: 10, backgroundColor: "rgba(0,0,0,.6)", paddingHorizontal: 3 },

  modeBadge:     { position: "absolute", top: 10, left: 10, backgroundColor: "rgba(46,204,113,.2)", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8 },
  modeBadgeCrit: { backgroundColor: "rgba(255,77,94,.25)" },
  modeBadgeTxt:  { color: "#fff", fontWeight: "700", fontSize: 12 },

  hud:    { position: "absolute", bottom: 10, left: 10, flexDirection: "row", gap: 12 },
  hudTxt: { color: "#fff", fontSize: 11, backgroundColor: "rgba(11,16,32,.7)", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },

  controls:   { flexDirection: "row", padding: 16, gap: 10 },
  smallBtn:   { backgroundColor: colors.surface, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10, marginTop: 10 },
  historyBtn: { borderWidth: 1, borderColor: colors.accent + "33" },
  btnTxt:     { color: colors.textPrimary, fontWeight: "600" },

  card:      { backgroundColor: colors.card, marginHorizontal: 16, marginBottom: 14, borderRadius: 14, padding: 16, borderWidth: 1, borderColor: colors.border },
  cardTitle: { color: colors.textSecondary, fontSize: 11, letterSpacing: 1, marginBottom: 12 },

  grid:        { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  metric:      { width: "47%", backgroundColor: colors.surface, padding: 12, borderRadius: 10 },
  metricLabel: { color: colors.textSecondary, fontSize: 11 },
  metricVal:   { color: colors.textPrimary, fontSize: 16, fontWeight: "700", marginTop: 4 },

  bigScore: { color: colors.textPrimary, fontSize: 30, fontWeight: "800" },
  lvl:      { fontWeight: "700", fontSize: 14 },

  barBg:   { height: 10, backgroundColor: colors.surface, borderRadius: 999, marginVertical: 10, overflow: "hidden" },
  barFill: { height: "100%", borderRadius: 999 },

  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  tag:  { color: colors.riskMedium, fontSize: 11, backgroundColor: "rgba(245,166,35,.15)", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
});
