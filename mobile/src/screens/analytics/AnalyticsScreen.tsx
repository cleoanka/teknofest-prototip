import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl, TouchableOpacity,
} from "react-native";
import { getStatistics, getQodProof, getEventsSummary, getHeatmap, ApiError } from "../../api/client";
import { colors, spacing, radius, font } from "../../theme";
import { Card, CardTitle, Pill } from "../../components/primitives";
import { ProgressBar } from "../../components/ProgressBar";
import { StatTile } from "../../components/StatTile";
import type { Statistics, QoDProof, HourlySummary, HeatmapRow } from "../../types/api";

const LEVEL_COLOR: Record<string, string> = {
  LOW: colors.ok, MEDIUM: colors.warn, HIGH: colors.orange, CRITICAL: colors.danger,
};

export default function AnalyticsScreen({ onError }: any) {
  const [stats, setStats] = useState<Statistics | null>(null);
  const [proof, setProof] = useState<QoDProof | null>(null);
  const [summary, setSummary] = useState<HourlySummary[]>([]);
  const [heat, setHeat] = useState<HeatmapRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [st, pr, sm, hm] = await Promise.all([
        getStatistics(3600),
        getQodProof(),
        getEventsSummary(24),
        getHeatmap(24),
      ]);
      setStats(st);
      setProof(pr);
      setSummary(sm.summary ?? []);
      setHeat(hm.rows ?? []);
    } catch (e) {
      if (e instanceof ApiError && e.kind === "auth") onError?.(e);
      else setError("Analitik verileri yüklenemedi.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, []);

  if (loading) {
    return <View style={s.center}><ActivityIndicator color={colors.accent} size="large" /></View>;
  }
  if (error) {
    return (
      <View style={s.center}>
        <Text style={s.errIcon}>⚠</Text>
        <Text style={s.errTxt}>{error}</Text>
        <TouchableOpacity style={s.retry} onPress={() => load()}>
          <Text style={s.retryTxt}>Tekrar Dene</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const dist = stats?.level_distribution ?? {};
  const maxCount = Math.max(1, ...summary.map(h => h.count));

  return (
    <ScrollView
      style={s.root}
      contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing.xxl, gap: spacing.md }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(true); }} tintColor={colors.accent} />}
    >
      {/* QoD %40 verimlilik kanıtı — jüri kriteri */}
      {proof && (
        <Card style={s.proofCard}>
          <CardTitle right={
            <Pill
              label={proof.meets_criterion ? "✓ KARŞILANDI" : "✗ ALTINDA"}
              color={proof.meets_criterion ? colors.ok : colors.danger}
            />
          }>QoD BANT VERİMLİLİĞİ (ÖTR %40)</CardTitle>

          <View style={s.proofRow}>
            <Text style={[s.proofPct, { color: proof.meets_criterion ? colors.ok : colors.orange }]}>
              %{proof.measured_efficiency_pct.toFixed(1)}
            </Text>
            <Text style={s.proofTarget}>hedef %{proof.target_efficiency_pct.toFixed(0)}</Text>
          </View>
          <ProgressBar
            value={proof.measured_efficiency_pct}
            color={proof.meets_criterion ? colors.ok : colors.orange}
            height={12}
          />
          <View style={s.proofMeta}>
            <Text style={s.proofMetaTxt}>Toplam döngü: {proof.total_qod_cycles}</Text>
            <Text style={s.proofMetaTxt}>Kritik: {proof.critical_mode_cycles}</Text>
            <Text style={s.proofMetaTxt}>Normal: {proof.normal_mode_cycles}</Text>
          </View>
          <Text style={s.proofBand}>
            Normal {proof.normal_bandwidth_mbps} Mbps · Kritik {proof.critical_bandwidth_mbps} Mbps
          </Text>
        </Card>
      )}

      {/* Özet istatistik kutuları */}
      <View style={s.tiles}>
        <StatTile label="TOPLAM OLAY" value={stats?.count ?? 0} width="48.5%" />
        <StatTile label="YÜKSEK RİSK" value={stats?.high_risk_count ?? 0} accent={colors.orange} width="48.5%" />
        <StatTile label="ORT. HIZ" value={stats?.avg_speed_kmh != null ? `${Math.round(stats.avg_speed_kmh)}` : "—"} sub="km/h" width="48.5%" />
        <StatTile label="QoD TETİK" value={stats?.qod_trigger_count ?? 0} accent={colors.cyan} width="48.5%" />
      </View>

      {/* Risk dağılımı */}
      <Card>
        <CardTitle>RİSK SEVİYESİ DAĞILIMI</CardTitle>
        {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const).map(lvl => {
          const count = (dist as any)[lvl] ?? 0;
          const total = Object.values(dist).reduce((a: number, b: any) => a + (b || 0), 0) || 1;
          const pct = (count / total) * 100;
          return (
            <View key={lvl} style={s.distRow}>
              <Text style={[s.distLabel, { color: LEVEL_COLOR[lvl] }]}>{lvl}</Text>
              <View style={s.distBarWrap}>
                <ProgressBar value={pct} color={LEVEL_COLOR[lvl]} height={8} />
              </View>
              <Text style={s.distCount}>{count}</Text>
            </View>
          );
        })}
      </Card>

      {/* Saatlik aktivite bar grafiği */}
      <Card>
        <CardTitle>SON 24 SAAT AKTİVİTE</CardTitle>
        {summary.length === 0 ? (
          <Text style={s.noData}>Henüz veri yok.</Text>
        ) : (
          <View style={s.chart}>
            {summary.slice(-24).map((h, i) => (
              <View key={i} style={s.barCol}>
                <View style={[s.bar, {
                  height: Math.max(3, (h.count / maxCount) * 90),
                  backgroundColor: colors.accent,
                }]} />
              </View>
            ))}
          </View>
        )}
        <Text style={s.chartAxis}>← eski · yeni →</Text>
      </Card>

      {/* Isı haritası */}
      {heat.length > 0 && (
        <Card>
          <CardTitle>ZAMAN × RİSK ISI HARİTASI</CardTitle>
          <View style={s.heatGrid}>
            {heat.slice(-24).map((row, i) => (
              <View key={i} style={s.heatCol}>
                {(["CRITICAL", "HIGH", "MEDIUM", "LOW"] as const).map(lvl => {
                  const v = (row as any)[lvl] ?? 0;
                  const intensity = v === 0 ? 0.08 : Math.min(1, 0.25 + v * 0.25);
                  return (
                    <View key={lvl} style={[s.heatCell, {
                      backgroundColor: LEVEL_COLOR[lvl],
                      opacity: intensity,
                    }]} />
                  );
                })}
              </View>
            ))}
          </View>
          <View style={s.heatLegend}>
            {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const).map(l => (
              <View key={l} style={s.legendItem}>
                <View style={[s.legendDot, { backgroundColor: LEVEL_COLOR[l] }]} />
                <Text style={s.legendTxt}>{l}</Text>
              </View>
            ))}
          </View>
        </Card>
      )}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, backgroundColor: colors.bg, alignItems: "center", justifyContent: "center", padding: spacing.xxl },

  proofCard: { borderColor: colors.accent + "44" },
  proofRow: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, marginBottom: spacing.sm },
  proofPct: { fontSize: 44, fontWeight: font.bold, lineHeight: 48 },
  proofTarget: { color: colors.textMuted, fontSize: font.body, marginBottom: 8 },
  proofMeta: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.md },
  proofMetaTxt: { color: colors.textDim, fontSize: font.tiny },
  proofBand: { color: colors.textMuted, fontSize: font.tiny, marginTop: spacing.sm },

  tiles: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, justifyContent: "space-between" },

  distRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  distLabel: { width: 72, fontSize: font.tiny, fontWeight: font.semibold },
  distBarWrap: { flex: 1 },
  distCount: { width: 32, textAlign: "right", color: colors.text, fontSize: font.small, fontWeight: font.semibold },

  chart: { flexDirection: "row", alignItems: "flex-end", height: 100, gap: 2, marginTop: spacing.sm },
  barCol: { flex: 1, alignItems: "center", justifyContent: "flex-end" },
  bar: { width: "70%", borderRadius: 2, minHeight: 3 },
  chartAxis: { color: colors.textMuted, fontSize: font.tiny, textAlign: "center", marginTop: spacing.sm },
  noData: { color: colors.textMuted, fontSize: font.small, textAlign: "center", paddingVertical: spacing.lg },

  heatGrid: { flexDirection: "row", gap: 2, marginTop: spacing.sm },
  heatCol: { flex: 1, gap: 2 },
  heatCell: { height: 14, borderRadius: 2 },
  heatLegend: { flexDirection: "row", gap: spacing.md, marginTop: spacing.md, justifyContent: "center" },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  legendDot: { width: 8, height: 8, borderRadius: 2 },
  legendTxt: { color: colors.textDim, fontSize: font.tiny },

  errIcon: { fontSize: 36, marginBottom: spacing.md },
  errTxt: { color: colors.danger, fontSize: font.body, textAlign: "center", marginBottom: spacing.lg },
  retry: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.md },
  retryTxt: { color: colors.text, fontWeight: font.medium },
});
