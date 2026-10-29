
export const SOFT_PROJECT_COLORS = [
  { name: 'clay', hex: '#966356' },
  { name: 'terracotta', hex: '#a7593d' },
  { name: 'copper', hex: '#a25e2b' },
  { name: 'saddle', hex: '#a17557' },
  { name: 'caramel', hex: '#c07e45' },
  { name: 'bronze', hex: '#817040' },
  { name: 'cobalt', hex: '#4e69ba' },
  { name: 'iris', hex: '#7b75e2' },
  { name: 'amethyst', hex: '#7457c2' },
  { name: 'ultraviolet', hex: '#a167cf' },
  { name: 'orchid', hex: '#b765a1' },
  { name: 'raspberry', hex: '#ad3f7f' },
] as const;

export type ProjectColor = string;

const HEX = /^#[0-9a-fA-F]{6}$/;

export function isHexColor(value: unknown): value is string {
  return typeof value === 'string' && HEX.test(value);
}

export function isProjectColor(value: unknown): value is ProjectColor {
  return isHexColor(value);
}

export function projectColorVar(color: string | null | undefined): string {
  return isHexColor(color) ? color.toLowerCase() : 'var(--oc-text-secondary)';
}

export function projectColorName(color: string | null | undefined): string | null {
  return SOFT_PROJECT_COLORS.find((swatch) => swatch.hex === color?.toLowerCase())?.name ?? null;
}

export const DEFAULT_PROJECT_COLOR = '#383838';

export function hexToRgb(hex: string): [number, number, number] {
    const h = isHexColor(hex) && hex.length === 7 ? hex : DEFAULT_PROJECT_COLOR;
    return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];
}

export function rgbToHex(r: number, g: number, b: number): string {
    const c = (n: number): string => Math.max(0, Math.min(255, Math.round(Number.isFinite(n) ? n : 0))).toString(16).padStart(2, '0');
    return `#${c(r)}${c(g)}${c(b)}`;
}
