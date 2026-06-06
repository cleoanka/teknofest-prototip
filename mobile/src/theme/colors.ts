/** Koyu tema renk paleti — tüm uygulama buradan beslenir. */
export const colors = {
  // Zemin katmanları (arkadan öne)
  bg:        "#0a0e1a",
  bgElev:    "#111729",
  card:      "#161d33",
  cardElev:  "#1d263f",
  border:    "#26304d",
  borderSoft:"#1c2540",

  // Metin
  text:      "#eef2ff",
  textDim:   "#9aa6c8",
  textMuted: "#5a678c",

  // Marka / vurgu
  accent:    "#3d82ff",
  accentDim: "#1e3a6b",
  cyan:      "#22d3ee",
  purple:    "#a78bfa",

  // Durum / risk
  ok:        "#34d399",   // LOW / sağlıklı
  warn:      "#fbbf24",   // MEDIUM
  orange:    "#fb923c",   // HIGH
  danger:    "#f43f5e",   // CRITICAL / hata

  // Tespit kutusu renkleri
  boxVehicle: "#3d82ff",
  boxPhone:   "#f43f5e",
  boxFace:    "#a78bfa",
  boxOther:   "#34d399",

  // Saydam katmanlar
  overlay:   "rgba(10,14,26,0.72)",
  scrim:     "rgba(0,0,0,0.55)",
} as const;

/** Risk skoruna (0–100) göre renk. */
export function riskColor(score: number): string {
  if (score >= 85) return colors.danger;
  if (score >= 60) return colors.orange;
  if (score >= 30) return colors.warn;
  return colors.ok;
}

/** Risk seviyesi etiketine göre renk. */
export function riskColorByLevel(level?: string): string {
  switch ((level || "").toUpperCase()) {
    case "CRITICAL": return colors.danger;
    case "HIGH":     return colors.orange;
    case "MEDIUM":   return colors.warn;
    default:         return colors.ok;
  }
}
