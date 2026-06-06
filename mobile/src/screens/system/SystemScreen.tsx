import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity, RefreshControl,
} from "react-native";
import { getHealth, getApiBase, setApiBase, ApiError } from "../../api/client";
import { useStatusSocket, SocketStatus } from "../../api/ws";
import { colors, spacing, radius, font } from "../../theme";
import { Card, CardTitle, Pill, StatusDot, Divider } from "../../components/primitives";
import { StatTile } from "../../components/StatTile";
import type { HealthInfo, StatusFrame } from "../../types/api";
import type { AuthMode } from "../../api/auth";

const SOCK_META: Record<SocketStatus, { c: string; t: string }> = {
  connected: { c: colors.ok, t: "Bağlı" },
  reconnecting: { c: colors.warn, t: "Yeniden bağlanıyor" },
  connecting: { c: colors.textMuted, t: "Bağlanıyor" },
  disconnected: { c: colors.danger, t: "Kopuk" },
};

export default function SystemScreen({ authMode, onError }: { authMode?: AuthMode; onError?: (e: unknown) => void }) {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [live, setLive] = useState<StatusFrame | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [addr, setAddr] = useState(getApiBase());

  const { status: sockStatus } = useStatusSocket(setLive, true);

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await getHealth());
    } catch (e) {
      if (e instanceof ApiError && e.kind === "auth") onError?.(e);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { loadHealth(); }, []);

  const applyAddr = () => { setApiBase(addr); setAddr(getApiBase()); loadHealth(); };

  const sm = SOCK_META[sockStatus];
  const verified = authMode === "verified";
  const crit = live?.qod_mode === "CRITICAL";

  return (
    <ScrollView
      style={s.root}
      contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.md }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadHealth(); }} tintColor={colors.accent} />}
    >
      {/* Kimlik doğrulama durumu (soft fallback rozeti) */}
      <Card style={{ borderColor: (verified ? colors.ok : colors.warn) + "44" }}>
        <CardTitle right={
          <Pill
            label={verified ? "✓ DOĞRULANDI" : "⚠ DOĞRULANMADI"}
            color={verified ? colors.ok : colors.warn}
          />
        }>SIM DOĞRULAMA (CAMARA)</CardTitle>
        <Text style={s.authTxt}>
          {authMode === "verified" && "Şebeke tabanlı sessiz doğrulama başarılı. Token aktif."}
          {authMode === "fallback-unverified" && "Doğrulama reddedildi — soft fallback ile açıldı. Gerçek doğrulama için config.ts'de softFallback'i kapat."}
          {authMode === "fallback-offline" && "Sunucuya ulaşılamadı — soft fallback ile açıldı. Sunucu adresini kontrol et."}
          {!authMode && "Doğrulama durumu bilinmiyor."}
        </Text>
      </Card>

      {/* Canlı bant durumu */}
      <Card style={{ borderColor: (crit ? colors.danger : colors.ok) + "33" }}>
        <CardTitle right={<><StatusDot color={sm.c} /></>}>5G BANT · CANLI</CardTitle>
        <View style={s.bandRow}>
          <Text style={[s.bandVal, { color: crit ? colors.danger : colors.ok }]}>
            {live?.bandwidth_mbps ?? "—"}
          </Text>
          <Text style={s.bandUnit}>Mbps</Text>
          <View style={{ flex: 1 }} />
          <Pill label={crit ? "KRİTİK" : "NORMAL"} color={crit ? colors.danger : colors.ok} />
        </View>
        <Text style={s.sockTxt}>WS: {sm.t} · Verimlilik %{((live?.bandwidth_efficiency ?? 0) * 100).toFixed(0)}</Text>
      </Card>

      {/* Canlı sistem metrikleri */}
      <View style={s.tiles}>
        <StatTile label="OLAY SAYISI" value={live?.event_count ?? health?.event_count ?? 0} width="48.5%" />
        <StatTile label="WS BAĞLANTI" value={live?.ws_connections ?? 0} accent={colors.cyan} width="48.5%" />
        <StatTile label="ÇALIŞMA SÜRESİ" value={fmtUptime(live?.uptime_s ?? health?.uptime_s ?? 0)} width="48.5%" />
        <StatTile label="AI MODU" value={health?.ai_mode ?? "—"} accent={colors.purple} width="48.5%" />
      </View>

      {/* Sunucu bilgisi */}
      <Card>
        <CardTitle>SUNUCU</CardTitle>
        <Row k="Sürüm" v={health?.version ?? "—"} />
        <Divider />
        <Row k="Dedektör" v={health?.detector ?? "—"} />
        <Divider />
        <Row k="Durum" v={health?.status ?? "—"} />

        <Text style={s.addrLabel}>Sunucu Adresi (geliştirme)</Text>
        <View style={s.addrRow}>
          <TextInput
            style={s.input}
            value={addr}
            onChangeText={setAddr}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="http://192.168.x.x:8000"
            placeholderTextColor={colors.textMuted}
          />
          <TouchableOpacity style={s.applyBtn} onPress={applyAddr}>
            <Text style={s.applyTxt}>Uygula</Text>
          </TouchableOpacity>
        </View>
        <Text style={s.hint}>Değişiklik sekme/uygulama yeniden açılışında tam etki eder.</Text>
      </Card>
    </ScrollView>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <View style={s.row}><Text style={s.k}>{k}</Text><Text style={s.v}>{v}</Text></View>;
}

function fmtUptime(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}dk`;
  return `${(sec / 3600).toFixed(1)}sa`;
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  authTxt: { color: colors.textDim, fontSize: font.small, lineHeight: 20 },

  bandRow: { flexDirection: "row", alignItems: "flex-end", gap: 6 },
  bandVal: { fontSize: 40, fontWeight: font.bold, lineHeight: 44 },
  bandUnit: { color: colors.textMuted, fontSize: font.body, marginBottom: 6 },
  sockTxt: { color: colors.textMuted, fontSize: font.tiny, marginTop: spacing.sm },

  tiles: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, justifyContent: "space-between" },

  row: { flexDirection: "row", justifyContent: "space-between", paddingVertical: spacing.sm },
  k: { color: colors.textDim, fontSize: font.body },
  v: { color: colors.text, fontSize: font.body, fontWeight: font.medium },

  addrLabel: { color: colors.textMuted, fontSize: font.tiny, letterSpacing: 0.5, marginTop: spacing.md, marginBottom: 6 },
  addrRow: { flexDirection: "row", gap: spacing.sm },
  input: { flex: 1, backgroundColor: colors.bgElev, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, color: colors.text, fontSize: font.small },
  applyBtn: { backgroundColor: colors.accent, paddingHorizontal: spacing.lg, justifyContent: "center", borderRadius: radius.md },
  applyTxt: { color: "#fff", fontWeight: font.semibold, fontSize: font.small },
  hint: { color: colors.textMuted, fontSize: font.tiny, marginTop: spacing.sm },
});
