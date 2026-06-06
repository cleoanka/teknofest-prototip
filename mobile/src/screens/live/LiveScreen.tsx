import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated, View, Text, TouchableOpacity, StyleSheet, ScrollView, Dimensions, Linking, Platform,
} from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import { useFrameSocket, SocketStatus } from "../../api/ws";
import { STREAM } from "../../config/env";
import { colors, spacing, radius, font, riskColor, riskColorByLevel } from "../../theme";
import { Card, CardTitle, Pill, StatusDot } from "../../components/primitives";
import { ProgressBar } from "../../components/ProgressBar";
import type { FrameResult } from "../../types/api";

const { width: SCREEN_W } = Dimensions.get("window");
const PREVIEW_W = SCREEN_W - spacing.lg * 2;
const PREVIEW_H = Math.round((PREVIEW_W * 9) / 16);

const STATUS_META: Record<SocketStatus, { c: string; t: string }> = {
  connected:    { c: colors.ok,     t: "Canlı" },
  reconnecting: { c: colors.warn,   t: "Yeniden bağlanıyor…" },
  connecting:   { c: colors.textMuted, t: "Bağlanıyor…" },
  disconnected: { c: colors.danger, t: "Bağlantı yok" },
};

const BOX_COLOR = (label: string) =>
  label === "vehicle" ? colors.boxVehicle
  : label === "phone" ? colors.boxPhone
  : label === "face"  ? colors.boxFace
  : colors.boxOther;

export default function LiveScreen() {
  const [perm, requestPerm] = useCameraPermissions();
  const [facing, setFacing] = useState<"back" | "front">("back");
  const [result, setResult] = useState<FrameResult | null>(null);
  const [shownScore, setShownScore] = useState(0);
  const camRef = useRef<CameraView>(null);
  const sent = useRef({ w: 640, h: 360 });

  const scoreAnim = useRef(new Animated.Value(0)).current;
  const pulse = useRef(new Animated.Value(0)).current;
  const pulseLoop = useRef<Animated.CompositeAnimation | null>(null);

  const crit = result?.mode === "CRITICAL";

  const onFrame = useCallback((f: FrameResult) => setResult(f), []);
  const { status, send } = useFrameSocket(onFrame, true);

  // İzin iste (sadece sorulabilir durumdaysa)
  useEffect(() => {
    if (perm && !perm.granted && perm.canAskAgain) requestPerm();
  }, [perm?.status]);

  // Kare yakalama döngüsü
  useEffect(() => {
    const id = setInterval(capture, 1000 / STREAM.sendFps);
    return () => clearInterval(id);
  }, []);

  const capture = async () => {
    if (!camRef.current) return;
    try {
      const pic = await camRef.current.takePictureAsync({
        base64: true, quality: STREAM.jpegQuality, skipProcessing: true,
      });
      if (pic?.base64) {
        sent.current = { w: pic.width, h: pic.height };
        send(JSON.stringify({
          frame: "data:image/jpeg;base64," + pic.base64,
          client_ts: Date.now() / 1000,
        }));
      }
    } catch {}
  };

  // Risk skoru animasyonu (sayı + bar birlikte)
  useEffect(() => {
    const target = result?.risk.score ?? 0;
    const id = scoreAnim.addListener(({ value }) => setShownScore(Math.round(value)));
    Animated.timing(scoreAnim, { toValue: target, duration: 450, useNativeDriver: false })
      .start(() => { scoreAnim.removeListener(id); setShownScore(target); });
    return () => scoreAnim.removeListener(id);
  }, [result?.risk.score]);

  // CRITICAL pulse
  useEffect(() => {
    pulseLoop.current?.stop();
    if (crit) {
      pulseLoop.current = Animated.loop(Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 600, useNativeDriver: false }),
        Animated.timing(pulse, { toValue: 0.2, duration: 600, useNativeDriver: false }),
      ]));
      pulseLoop.current.start();
    } else {
      Animated.timing(pulse, { toValue: 0, duration: 300, useNativeDriver: false }).start();
    }
    return () => pulseLoop.current?.stop();
  }, [crit]);

  const borderColor = pulse.interpolate({
    inputRange: [0, 0.2, 1],
    outputRange: ["rgba(244,63,94,0)", "rgba(244,63,94,0.35)", "rgba(244,63,94,1)"],
  });

  // İzin durumları
  if (!perm) {
    return <View style={s.fill}><Text style={s.dim}>Kamera izni kontrol ediliyor…</Text></View>;
  }
  if (!perm.granted) {
    return (
      <View style={s.fill}>
        <Text style={s.permIcon}>📷</Text>
        <Text style={s.permTitle}>Kamera İzni Gerekli</Text>
        <Text style={s.permBody}>
          Canlı yol analizi için kamera erişimi şart.
        </Text>
        <TouchableOpacity
          style={s.permBtn}
          onPress={() => (perm.canAskAgain ? requestPerm() : Linking.openSettings())}
        >
          <Text style={s.permBtnTxt}>{perm.canAskAgain ? "İzin Ver" : "Ayarları Aç"}</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const sx = PREVIEW_W / sent.current.w;
  const sy = PREVIEW_H / sent.current.h;
  const sm = STATUS_META[status];
  const score = result?.risk.score ?? 0;
  const factors = result?.risk.factors ?? [];

  return (
    <ScrollView style={s.root} contentContainerStyle={{ paddingBottom: spacing.xxl }}>
      {/* Üst durum çubuğu */}
      <View style={s.topbar}>
        <View style={s.row}>
          <StatusDot color={sm.c} />
          <Text style={s.topTxt}>{sm.t}</Text>
        </View>
        <Pill
          label={crit ? "● KRİTİK" : "● NORMAL"}
          color={crit ? colors.danger : colors.ok}
        />
      </View>

      {/* Kamera + overlay */}
      <Animated.View style={[s.previewWrap, { borderColor }]}>
        <View style={s.preview}>
          <CameraView ref={camRef} style={StyleSheet.absoluteFill} facing={facing} />

          {(result?.detections ?? []).map((d, i) => {
            const c = BOX_COLOR(d.label);
            return (
              <View key={i} style={[s.box, {
                left: d.bbox.x1 * sx, top: d.bbox.y1 * sy,
                width: (d.bbox.x2 - d.bbox.x1) * sx, height: (d.bbox.y2 - d.bbox.y1) * sy,
                borderColor: c,
              }]}>
                <Text style={[s.boxLabel, { backgroundColor: c }]}>
                  {d.label} {(d.confidence * 100) | 0}%
                </Text>
              </View>
            );
          })}

          {/* HUD */}
          <View style={s.hud}>
            <HudChip label={`${result?.qod.bandwidth_mbps ?? 5} Mbps`} />
            <HudChip label={crit ? "1080p" : "480p"} />
            <HudChip label={`${(result?.fps ?? 0).toFixed(1)} FPS`} />
            <HudChip label={`${(result?.total_latency_ms ?? 0) | 0} ms`} />
          </View>
        </View>
      </Animated.View>

      {/* Kamera kontrol */}
      <View style={s.controls}>
        <TouchableOpacity style={s.ctrlBtn} onPress={() => setFacing(f => f === "back" ? "front" : "back")}>
          <Text style={s.ctrlTxt}>⟲ Kamera Çevir</Text>
        </TouchableOpacity>
      </View>

      {/* Risk paneli */}
      <Card style={{ marginHorizontal: spacing.lg, marginTop: spacing.md }}>
        <CardTitle right={
          <Text style={[s.level, { color: riskColorByLevel(result?.risk.level) }]}>
            {result?.risk.level ?? "LOW"}
          </Text>
        }>SÜRÜCÜ RİSK SKORU</CardTitle>

        <View style={s.scoreRow}>
          <Text style={[s.score, { color: riskColor(score) }]}>{shownScore}</Text>
          <Text style={s.scoreMax}>/100</Text>
        </View>
        <ProgressBar value={score} color={riskColor(score)} height={12} />

        {factors.length > 0 && (
          <View style={s.factors}>
            {factors.map((f, i) => <Pill key={i} label={f} color={colors.warn} />)}
          </View>
        )}
      </Card>

      {/* Araç & plaka */}
      <Card style={{ marginHorizontal: spacing.lg, marginTop: spacing.md }}>
        <CardTitle>ARAÇ & PLAKA</CardTitle>
        <View style={s.grid}>
          <Mini label="Plaka" value={result?.vehicle.plate.text || "—"} wide />
          <Mini label="Hız" value={result?.vehicle.speed_kmh != null ? `${Math.round(result.vehicle.speed_kmh)} km/h` : "—"} />
          <Mini label="Tip" value={result?.vehicle.vtype || "—"} />
          <Mini label="Renk" value={result?.vehicle.color || "—"} />
          <Mini label="Yön" value={result?.vehicle.swerving ? "Zigzag!" : "Düz"} />
        </View>
      </Card>

      {/* QoD tetik */}
      <Card style={{ marginHorizontal: spacing.lg, marginTop: spacing.md }}>
        <CardTitle right={<Pill label={crit ? "AKTİF" : "Beklemede"} color={crit ? colors.danger : colors.textDim} />}>
          QoD · 5G BANT YÖNETİMİ
        </CardTitle>
        <Text style={s.kv}>Sebep: <Text style={s.kvVal}>{result?.qod.last_trigger_reason || "—"}</Text></Text>
        <Text style={s.kv}>Oturum yaşı: <Text style={s.kvVal}>{(result?.qod.session_age_s ?? 0).toFixed(1)}s</Text></Text>
      </Card>
    </ScrollView>
  );
}

function HudChip({ label }: { label: string }) {
  return <View style={s.hudChip}><Text style={s.hudTxt}>{label}</Text></View>;
}

function Mini({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <View style={[s.mini, wide && { width: "100%" }]}>
      <Text style={s.miniLabel}>{label}</Text>
      <Text style={s.miniVal} numberOfLines={1}>{value}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  fill: { flex: 1, backgroundColor: colors.bg, alignItems: "center", justifyContent: "center", padding: spacing.xxl },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  dim: { color: colors.textDim, fontSize: font.body },

  topbar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg },
  topTxt: { color: colors.textDim, fontSize: font.small, fontWeight: font.medium },

  previewWrap: { marginHorizontal: spacing.lg, borderRadius: radius.lg, borderWidth: 2 },
  preview: { width: PREVIEW_W, height: PREVIEW_H, borderRadius: radius.md, overflow: "hidden", backgroundColor: "#000" },
  box: { position: "absolute", borderWidth: 2, borderRadius: 4 },
  boxLabel: { color: "#fff", fontSize: 9, fontWeight: font.semibold, paddingHorizontal: 4, paddingVertical: 1, alignSelf: "flex-start", overflow: "hidden", borderRadius: 3 },

  hud: { position: "absolute", bottom: spacing.sm, left: spacing.sm, right: spacing.sm, flexDirection: "row", flexWrap: "wrap", gap: 6 },
  hudChip: { backgroundColor: colors.overlay, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.sm },
  hudTxt: { color: "#fff", fontSize: font.tiny, fontWeight: font.medium },

  controls: { flexDirection: "row", paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  ctrlBtn: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.md },
  ctrlTxt: { color: colors.text, fontWeight: font.medium, fontSize: font.small },

  level: { fontSize: font.small, fontWeight: font.bold },
  scoreRow: { flexDirection: "row", alignItems: "flex-end", gap: 6, marginBottom: spacing.sm },
  score: { fontSize: 46, fontWeight: font.bold, lineHeight: 50 },
  scoreMax: { color: colors.textMuted, fontSize: font.body, marginBottom: 8 },
  factors: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.md },

  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  mini: { width: "47.5%", backgroundColor: colors.bgElev, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.borderSoft },
  miniLabel: { color: colors.textMuted, fontSize: font.tiny },
  miniVal: { color: colors.text, fontSize: font.h3, fontWeight: font.semibold, marginTop: 4 },

  kv: { color: colors.textDim, fontSize: font.small, marginTop: 4 },
  kvVal: { color: colors.text, fontWeight: font.medium },

  permIcon: { fontSize: 48, marginBottom: spacing.lg },
  permTitle: { color: colors.text, fontSize: font.h3, fontWeight: font.semibold, marginBottom: spacing.sm },
  permBody: { color: colors.textDim, fontSize: font.body, textAlign: "center", marginBottom: spacing.xl },
  permBtn: { backgroundColor: colors.accent, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.md },
  permBtnTxt: { color: "#fff", fontWeight: font.semibold, fontSize: font.body },
});
