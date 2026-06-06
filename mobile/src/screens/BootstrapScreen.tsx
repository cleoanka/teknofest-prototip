import React, { useEffect, useState } from "react";
import { View, Text, ActivityIndicator, TouchableOpacity, StyleSheet } from "react-native";
import { silentVerify, AuthMode } from "../api/auth";
import { colors, spacing, radius, font } from "../theme";

/**
 * Açılış ekranı — sessiz CAMARA doğrulamasını yürütür.
 * Başarılı (veya soft fallback) → onReady(mode). Başarısız (fallback kapalı) → hata + tekrar dene.
 */
export default function BootstrapScreen({ onReady }: { onReady: (mode: AuthMode) => void }) {
  const [failReason, setFailReason] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const run = async () => {
    setBusy(true);
    setFailReason(null);
    const res = await silentVerify();
    if (res.ok) {
      onReady(res.mode);
    } else {
      setFailReason(res.reason);
      setBusy(false);
    }
  };

  useEffect(() => { run(); }, []);

  return (
    <View style={s.root}>
      <Text style={s.logo}>🛡️</Text>
      <Text style={s.title}>Akıllı Yol Güvenliği</Text>
      <Text style={s.subtitle}>5G & Yapay Zeka</Text>

      {busy ? (
        <View style={s.statusBox}>
          <ActivityIndicator color={colors.accent} />
          <Text style={s.statusTxt}>Şebeke doğrulaması yapılıyor…</Text>
        </View>
      ) : (
        <View style={s.statusBox}>
          <Text style={s.failIcon}>🔒</Text>
          <Text style={s.failTitle}>Doğrulama Başarısız</Text>
          <Text style={s.failTxt}>{failReason}</Text>
          <TouchableOpacity style={s.retry} onPress={run}>
            <Text style={s.retryTxt}>Tekrar Dene</Text>
          </TouchableOpacity>
          <Text style={s.hint}>
            Geliştirme için config/env.ts → AUTH.softFallback = true yapabilirsin.
          </Text>
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg, alignItems: "center", justifyContent: "center", padding: spacing.xxl },
  logo: { fontSize: 64, marginBottom: spacing.lg },
  title: { color: colors.text, fontSize: font.h1, fontWeight: font.bold },
  subtitle: { color: colors.textDim, fontSize: font.body, marginTop: 4, marginBottom: spacing.xxl },
  statusBox: { alignItems: "center", gap: spacing.md },
  statusTxt: { color: colors.textDim, fontSize: font.small },
  failIcon: { fontSize: 40 },
  failTitle: { color: colors.text, fontSize: font.h3, fontWeight: font.semibold },
  failTxt: { color: colors.danger, fontSize: font.small, textAlign: "center" },
  retry: { backgroundColor: colors.accent, paddingHorizontal: spacing.xl, paddingVertical: spacing.md, borderRadius: radius.md, marginTop: spacing.sm },
  retryTxt: { color: "#fff", fontWeight: font.semibold },
  hint: { color: colors.textMuted, fontSize: font.tiny, textAlign: "center", marginTop: spacing.md },
});
