import React, { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ActivityIndicator } from "react-native";
import { silentVerify } from "../api/client";

export default function LoginScreen({ onSuccess }: { onSuccess: (token: string | null) => void }) {
  const [deviceToken, setDeviceToken] = useState("device-guard-01");
  const [phone, setPhone] = useState("+905320001122");
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const verify = async () => {
    setBusy(true); setStatus("Şebeke üzerinden sessiz doğrulanıyor…");
    try {
      const res = await silentVerify(deviceToken, phone);
      if (res.devicePhoneNumberVerified) {
        setStatus("✓ Doğrulandı");
        setTimeout(() => onSuccess(res.token), 400);
      } else {
        setStatus("✗ SIM ↔ numara eşleşmedi");
      }
    } catch (e: any) {
      setStatus("Bağlantı hatası: " + e.message);
    } finally { setBusy(false); }
  };

  return (
    <View style={s.wrap}>
      <View style={s.logo}><Text style={s.logoTxt}>YG</Text></View>
      <Text style={s.title}>Akıllı Yol Güvenliği</Text>
      <Text style={s.sub}>CAMARA Number Verification ile sessiz SIM doğrulama — SMS/kod yok.</Text>

      <TextInput style={s.input} value={deviceToken} onChangeText={setDeviceToken}
        placeholder="Cihaz token" placeholderTextColor="#8a97bd" autoCapitalize="none" />
      <TextInput style={s.input} value={phone} onChangeText={setPhone}
        placeholder="Hat numarası" placeholderTextColor="#8a97bd" keyboardType="phone-pad" />

      <TouchableOpacity style={s.btn} onPress={verify} disabled={busy}>
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={s.btnTxt}>Sessiz Doğrula & Giriş</Text>}
      </TouchableOpacity>
      <Text style={s.status}>{status}</Text>
      <Text style={s.hint}>Demo: device-guard-01 → +905320001122</Text>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flex: 1, justifyContent: "center", padding: 28 },
  logo: { width: 64, height: 64, borderRadius: 16, backgroundColor: "#2f7bff", alignSelf: "center", alignItems: "center", justifyContent: "center", marginBottom: 18 },
  logoTxt: { color: "#fff", fontWeight: "800", fontSize: 26 },
  title: { color: "#e6ecff", fontSize: 24, fontWeight: "800", textAlign: "center" },
  sub: { color: "#8a97bd", fontSize: 13, textAlign: "center", marginVertical: 14 },
  input: { backgroundColor: "#1b2540", color: "#e6ecff", borderRadius: 12, padding: 14, marginBottom: 12, borderWidth: 1, borderColor: "#25304f" },
  btn: { backgroundColor: "#2f7bff", borderRadius: 12, padding: 16, alignItems: "center", marginTop: 6 },
  btnTxt: { color: "#fff", fontWeight: "700", fontSize: 16 },
  status: { color: "#2ecc71", textAlign: "center", marginTop: 14, minHeight: 20 },
  hint: { color: "#8a97bd", fontSize: 11, textAlign: "center", marginTop: 8 },
});
