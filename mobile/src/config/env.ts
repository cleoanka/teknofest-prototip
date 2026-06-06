/**
 * Uygulama yapılandırması — tek dosyada toplandı.
 * Geliştirici burayı düzenler; uygulama kullanıcıya hiçbir ayar sormaz.
 */

// ── Sunucu adresi ─────────────────────────────────────────────────────────────
// Backend'in çalıştığı makinenin LAN adresi. Telefon ve bilgisayar AYNI Wi-Fi'de
// olmalı. Mac'te `ipconfig getifaddr en0`, Windows'ta `ipconfig` ile öğren.
// Çalışma zamanında Sistem sekmesinden de değiştirilebilir (geliştirme kolaylığı).
export const DEFAULT_API_BASE = "http://192.168.1.20:8000";

// ── Kimlik doğrulama (CAMARA Number Verification — sessiz SIM doğrulama) ───────
export const AUTH = {
  /**
   * SOFT FALLBACK — geçici geliştirme kolaylığı.
   *
   * Number Verification normalde "sessiz" çalışır: cihazın SIM'i şebeke tarafından
   * arka planda doğrulanır, kullanıcı hiçbir şey girmez. Final yarışmada Turkcell
   * gerçek doğrulamayı sağlar.
   *
   *   true  → Doğrulama başarısız olsa bile (backend kapalı / ağ yok / SIM eşleşmedi)
   *           uygulama yine de AÇILIR. Sistem sekmesinde "⚠ Doğrulanmadı" rozeti
   *           görünür, böylece fallback'in devrede olduğunu fark edersin.
   *
   *   false → Doğrulama başarısızsa uygulama AÇILMAZ, hata ekranı gösterir.
   *           ⚠️ GERÇEK DOĞRULAMAYI TEST ETMEK İÇİN BUNU false YAP.
   *           false iken içeri girebiliyorsan, gerçek number-verification çalışıyor demektir.
   */
  softFallback: true,

  /**
   * Sessiz doğrulamada kullanılan cihaz kimliği ve hat numarası.
   * GERÇEKTE bunlar cihazın SIM'inden / şebekeden gelir — burada gömülü değerler
   * sadece mock backend'i test etmek içindir.
   *
   * Mock backend SIM kaydı (backend/camara/number_verification.py):
   *   device-demo-token → +905551112233
   *   device-guard-01   → +905320001122
   *   device-guard-02   → +905340001133
   */
  deviceToken: "device-demo-token",
  phoneNumber: "+905551112233",
} as const;

// ── Kamera / akış ─────────────────────────────────────────────────────────────
export const STREAM = {
  sendFps: 5,          // saniyede kaç kare backend'e gönderilsin
  jpegQuality: 0.4,    // kare JPEG kalitesi (0–1) — düşük = az bant
} as const;
