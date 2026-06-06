import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, TouchableOpacity, FlatList,
  StyleSheet, ActivityIndicator, RefreshControl,
} from "react-native";
import { fetchEvents, ApiError } from "../api/client";
import { MOCK_MODE } from "../config";
import { MOCK_EVENTS } from "../mocks/events";
import { StoredEvent } from "../types";

interface Props {
  onOpenEvent: (ev: StoredEvent) => void;
  onBack: () => void;
  onError?: (e: unknown) => void;
}

export default function EventListScreen({ onOpenEvent, onBack, onError }: Props) {
  const [events, setEvents] = useState<StoredEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      if (MOCK_MODE) {
        // Mock modda kısa gecikme simüle et, sonra sahte veriyi döndür
        await new Promise<void>((r) => setTimeout(r, 600));
        setEvents(MOCK_EVENTS);
      } else {
        const data = await fetchEvents(0, 50);
        setEvents(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      if (e instanceof ApiError && e.kind === "auth") {
        onError?.(e);
      } else {
        setError("Olaylar yüklenemedi. Sunucu bağlantısını kontrol et.");
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, []);

  const onRefresh = () => { setRefreshing(true); load(true); };

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator color="#2f7bff" size="large" />
        <Text style={s.dim}>Olaylar yükleniyor…</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={s.center}>
        <Text style={s.errorIcon}>⚠</Text>
        <Text style={s.errorTxt}>{error}</Text>
        <TouchableOpacity style={s.retryBtn} onPress={() => load()}>
          <Text style={s.retryTxt}>Tekrar Dene</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={s.root}>
      <View style={s.header}>
        <TouchableOpacity onPress={onBack}>
          <Text style={s.back}>‹ Geri</Text>
        </TouchableOpacity>
        <Text style={s.title}>Geçmiş Olaylar</Text>
        <Text style={s.count}>{events.length} kayıt</Text>
      </View>

      <FlatList
        data={events}
        keyExtractor={(_, i) => String(i)}
        contentContainerStyle={events.length === 0 ? s.emptyContainer : s.listContent}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor="#2f7bff" />}
        ListEmptyComponent={
          <View style={s.center}>
            <Text style={s.emptyIcon}>📋</Text>
            <Text style={s.dim}>Henüz kayıtlı olay yok.</Text>
          </View>
        }
        renderItem={({ item }) => (
          <TouchableOpacity style={s.card} onPress={() => onOpenEvent(item)} activeOpacity={0.7}>
            <View style={s.cardTop}>
              <Text style={s.plate}>{item.plate || "Plaka yok"}</Text>
              <RiskBadge level={item.risk_level} score={item.risk_score} />
            </View>
            <View style={s.cardBottom}>
              <Text style={s.meta}>
                {item.vtype || "Araç"} · {item.speed_kmh != null ? item.speed_kmh + " km/h" : "—"}
              </Text>
              <Text style={s.ts}>
                {new Date(item.ts * 1000).toLocaleString("tr-TR")}
              </Text>
            </View>
            {item.factors ? (
              <Text style={s.factors} numberOfLines={1}>
                {item.factors.split(",").map(f => f.trim()).filter(Boolean).join(" · ")}
              </Text>
            ) : null}
          </TouchableOpacity>
        )}
      />
    </View>
  );
}

function RiskBadge({ level, score }: { level: string; score: number }) {
  const color = riskColor(score);
  return (
    <View style={[s.badge, { backgroundColor: color + "22", borderColor: color + "66" }]}>
      <Text style={[s.badgeTxt, { color }]}>{level}</Text>
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
  count: { color: "#8a97bd", fontSize: 13, minWidth: 50, textAlign: "right" },
  listContent: { padding: 12, gap: 10 },
  emptyContainer: { flex: 1 },
  card: {
    backgroundColor: "#131a2e", borderRadius: 14, padding: 14,
    borderWidth: 1, borderColor: "#25304f",
  },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 },
  plate: { color: "#e6ecff", fontSize: 17, fontWeight: "800", letterSpacing: 1 },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, borderWidth: 1 },
  badgeTxt: { fontSize: 12, fontWeight: "700" },
  cardBottom: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  meta: { color: "#8a97bd", fontSize: 13 },
  ts: { color: "#4a567a", fontSize: 12 },
  factors: { color: "#f5a623", fontSize: 11, marginTop: 8 },
  dim: { color: "#8a97bd", fontSize: 14, marginTop: 12, textAlign: "center" },
  emptyIcon: { fontSize: 40, marginBottom: 12 },
  errorIcon: { fontSize: 40, marginBottom: 12 },
  errorTxt: { color: "#ff4d5e", fontSize: 14, textAlign: "center", marginBottom: 20 },
  retryBtn: { backgroundColor: "#1b2540", paddingHorizontal: 24, paddingVertical: 12, borderRadius: 10 },
  retryTxt: { color: "#e6ecff", fontWeight: "600" },
});
