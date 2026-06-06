import React from "react";
import { View, Text, TouchableOpacity, StyleSheet, Linking, Platform } from "react-native";

interface Props {
  /** true → kalıcı red (Ayarlar gerekli), false → tekrar sorulabilir */
  permanent: boolean;
  onRequestAgain: () => void;
}

export default function PermissionDenied({ permanent, onRequestAgain }: Props) {
  const openSettings = () => Linking.openSettings();

  return (
    <View style={s.root}>
      <Text style={s.icon}>📷</Text>
      <Text style={s.title}>Kamera İzni Gerekli</Text>

      {permanent ? (
        <>
          <Text style={s.body}>
            Kamera izni kalıcı olarak reddedildi.{"\n"}
            Uygulamayı kullanmak için cihaz ayarlarından izin ver.
          </Text>
          <Text style={s.hint}>
            {Platform.OS === "ios"
              ? "Ayarlar › Gizlilik ve Güvenlik › Kamera"
              : "Ayarlar › Uygulamalar › Yol Güvenliği › İzinler"}
          </Text>
          <TouchableOpacity style={s.btn} onPress={openSettings}>
            <Text style={s.btnTxt}>Ayarları Aç</Text>
          </TouchableOpacity>
        </>
      ) : (
        <>
          <Text style={s.body}>
            Kamera izni olmadan canlı akış başlatılamaz.{"\n"}
            Devam etmek için izin ver.
          </Text>
          <TouchableOpacity style={s.btn} onPress={onRequestAgain}>
            <Text style={s.btnTxt}>İzin Ver</Text>
          </TouchableOpacity>
        </>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#0b1020",
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
  },
  icon: { fontSize: 48, marginBottom: 20 },
  title: { color: "#e6ecff", fontSize: 20, fontWeight: "700", marginBottom: 14, textAlign: "center" },
  body: { color: "#8a97bd", fontSize: 14, textAlign: "center", lineHeight: 22, marginBottom: 10 },
  hint: { color: "#4a567a", fontSize: 12, textAlign: "center", marginBottom: 28, fontStyle: "italic" },
  btn: {
    backgroundColor: "#2f7bff",
    paddingHorizontal: 32,
    paddingVertical: 14,
    borderRadius: 12,
    marginTop: 8,
  },
  btnTxt: { color: "#fff", fontWeight: "700", fontSize: 15 },
});
