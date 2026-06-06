export const colors = {
  // Zemin katmanları
  bg:      "#0b1020",
  card:    "#131a2e",
  surface: "#1b2540",
  border:  "#25304f",

  // Yazı
  textPrimary:   "#e6ecff",
  textSecondary: "#8a97bd",
  textMuted:     "#4a567a",

  // Vurgu
  accent: "#2f7bff",
  danger: "#ff4d5e",

  // Risk seviyeleri
  riskLow:      "#2ecc71",
  riskMedium:   "#f5a623",
  riskHigh:     "#ff8a50",
  riskCritical: "#ff4d5e",
} as const;

/** Risk skoruna göre renk döndürür (0-100) */
export function riskColor(score: number): string {
  if (score >= 85) return colors.riskCritical;
  if (score >= 60) return colors.riskHigh;
  if (score >= 30) return colors.riskMedium;
  return colors.riskLow;
}

/** Risk seviyesi string'ine göre renk döndürür */
export function riskColorByLevel(level?: string): string {
  return riskColor(
    level === "CRITICAL" ? 90 : level === "HIGH" ? 70 : level === "MEDIUM" ? 40 : 0,
  );
}
