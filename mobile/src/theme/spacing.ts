/** Tutarlı boşluk, köşe yarıçapı ve tipografi ölçekleri. */

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 22,
  pill: 999,
} as const;

export const font = {
  // boyutlar
  h1: 28,
  h2: 22,
  h3: 18,
  body: 15,
  small: 13,
  tiny: 11,
  // ağırlıklar
  bold: "800" as const,
  semibold: "700" as const,
  medium: "600" as const,
  regular: "400" as const,
};
