import React, { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity,
  StyleSheet, ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { setCredentials, verifyConnection } from "../api/client";

interface Props {
  onSuccess: (token: string) => void;
}

export default function LoginScreen({ onSuccess }: Props) {
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = async () => {
    if (!url.trim()) { setError("Sunucu adresi girin."); return; }
    setLoading(true);
    setError(null);
    try {
      await verifyConnection(url.trim(), token.trim());
      setCredentials(url.trim(), token.trim());
      onSuccess(token.trim());
    } catch (e: any) {
      setError(
        e?.name === "TimeoutError"
          ? "Sunucuya ulaşılamadı — zaman aşımı."
          : `Bağlantı hatası: ${e?.message ?? "Bilinmeyen hata"}`,
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={s.root}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <Text style={s.logo}>🛡</Text>
      <Text style={s.title}>Yol Güvenliği</Text>
      <Text style={s.subtitle}>Sunucu bağlantısı</Text>

      <View style={s.form}>
        <Text style={s.label}>Sunucu Adresi</Text>
        <TextInput
          style={s.input}
          placeholder="http://192.168.x.x:8000"
          placeholderTextColor="#4a567a"
          value={url}
          onChangeText={setUrl}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />

        <Text style={s.label}>Token (isteğe bağlı)</Text>
        <TextInput
          style={s.input}
          placeholder="Bearer token"
          placeholderTextColor="#4a567a"
          value={token}
          onChangeText={setToken}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry
        />

        {error ? <Text style={s.error}>{error}</Text> : null}

        <TouchableOpacity
          style={[s.btn, loading && s.btnDisabled]}
          onPress={connect}
          disabled={loading}
          activeOpacity={0.8}
        >
          {loading
            ? <ActivityIndicator color="#fff" />
            : <Text style={s.btnTxt}>Bağlan</Text>}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0b1020", alignItems: "center", justifyContent: "center", padding: 32 },
  logo: { fontSize: 56, marginBottom: 16 },
  title: { color: "#e6ecff", fontSize: 28, fontWeight: "800" },
  subtitle: { color: "#8a97bd", fontSize: 14, marginBottom: 40 },
  form: { width: "100%", maxWidth: 360 },
  label: { color: "#8a97bd", fontSize: 12, letterSpacing: 0.5, marginBottom: 6 },
  input: {
    backgroundColor: "#131a2e", borderWidth: 1, borderColor: "#25304f",
    borderRadius: 12, padding: 14, color: "#e6ecff", fontSize: 15, marginBottom: 18,
  },
  error: { color: "#ff4d5e", fontSize: 13, marginBottom: 16, textAlign: "center" },
  btn: {
    backgroundColor: "#2f7bff", borderRadius: 12,
    paddingVertical: 16, alignItems: "center", marginTop: 4,
  },
  btnDisabled: { opacity: 0.6 },
  btnTxt: { color: "#fff", fontWeight: "700", fontSize: 16 },
});
