import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, TouchableOpacity, FlatList, StyleSheet, ActivityIndicator, RefreshControl,
} from "react-native";
import { getEvents, ApiError } from "../../api/client";
import { colors, spacing, radius, font } from "../../theme";
import { RiskBadge } from "../../components/RiskBadge";
import { EmptyState } from "../../components/primitives";
import type { EventRecord } from "../../types/api";

const LEVELS = ["TÜMÜ", "LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;

export default function EventsScreen({ navigation, onError }: any) {
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState<string>("TÜMÜ");

  const load = useCallback(async (lvl: string, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await getEvents({
        limit: 100, minScore: 0,
        level: lvl === "TÜMÜ" ? undefined : lvl,
      });
      setEvents(Array.isArray(data) ? data : []);
    } catch (e) {
      if (e instanceof ApiError && e.kind === "auth") onError?.(e);
      else setError("Olaylar yüklenemedi. Sunucu bağlantısını kontrol et.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(level); }, [level]);

  return (
    <View style={s.root}>
      {/* Filtre çubuğu */}
      <View style={s.filterBar}>
        {LEVELS.map(l => {
          const active = l === level;
          return (
            <TouchableOpacity
              key={l}
              onPress={() => setLevel(l)}
              style={[s.chip, active && s.chipActive]}
            >
              <Text style={[s.chipTxt, active && s.chipTxtActive]}>{l}</Text>
            </TouchableOpacity>
          );
        })}
      </View>

      {loading ? (
        <View style={s.center}><ActivityIndicator color={colors.accent} size="large" /></View>
      ) : error ? (
        <View style={s.center}>
          <Text style={s.errIcon}>⚠</Text>
          <Text style={s.errTxt}>{error}</Text>
          <TouchableOpacity style={s.retry} onPress={() => load(level)}>
            <Text style={s.retryTxt}>Tekrar Dene</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={events}
          keyExtractor={(e, i) => String(e.id ?? i)}
          contentContainerStyle={events.length ? s.list : s.listEmpty}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(level, true); }}
              tintColor={colors.accent}
            />
          }
          ListEmptyComponent={<EmptyState icon="📋" text="Bu filtreye uygun olay yok." />}
          renderItem={({ item }) => (
            <TouchableOpacity
              activeOpacity={0.7}
              style={s.card}
              onPress={() => navigation.navigate("EventDetail", { event: item })}
            >
              <View style={s.cardTop}>
                <Text style={s.plate}>{item.plate || "Plaka yok"}</Text>
                <RiskBadge level={String(item.risk_level)} score={item.risk_score} size="sm" />
              </View>
              <View style={s.cardBottom}>
                <Text style={s.meta}>
                  {item.vtype || "Araç"} · {item.speed_kmh != null ? `${Math.round(item.speed_kmh)} km/h` : "—"}
                </Text>
                <Text style={s.time}>{new Date(item.ts * 1000).toLocaleString("tr-TR")}</Text>
              </View>
              {item.factors ? (
                <Text style={s.factors} numberOfLines={1}>
                  {item.factors.split(",").map(f => f.trim()).filter(Boolean).join(" · ")}
                </Text>
              ) : null}
            </TouchableOpacity>
          )}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xxl },

  filterBar: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.sm },
  chip: { paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill, backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.accentDim, borderColor: colors.accent },
  chipTxt: { color: colors.textDim, fontSize: font.tiny, fontWeight: font.semibold },
  chipTxtActive: { color: colors.text },

  list: { padding: spacing.lg, gap: spacing.md },
  listEmpty: { flexGrow: 1, justifyContent: "center" },
  card: { backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border },
  cardTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  plate: { color: colors.text, fontSize: font.h3, fontWeight: font.bold, letterSpacing: 1 },
  cardBottom: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  meta: { color: colors.textDim, fontSize: font.small },
  time: { color: colors.textMuted, fontSize: font.tiny },
  factors: { color: colors.warn, fontSize: font.tiny, marginTop: spacing.sm },

  errIcon: { fontSize: 36, marginBottom: spacing.md },
  errTxt: { color: colors.danger, fontSize: font.body, textAlign: "center", marginBottom: spacing.lg },
  retry: { backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.md },
  retryTxt: { color: colors.text, fontWeight: font.medium },
});
