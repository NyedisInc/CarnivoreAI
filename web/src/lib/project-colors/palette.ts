
export const SOFT_PROJECT_COLORS = [
  { name: 'crimson', hex: '#e6495c' },
  { name: 'tangerine', hex: '#e67329' },
  { name: 'amber', hex: '#c99214' },
  { name: 'lime', hex: '#6ea61c' },
  { name: 'emerald', hex: '#1ea662' },
  { name: 'teal', hex: '#12a392' },
  { name: 'cyan', hex: '#1c9ed6' },
  { name: 'cobalt', hex: '#4a80eb' },
  { name: 'indigo', hex: '#7a6af0' },
  { name: 'violet', hex: '#ae62eb' },
  { name: 'magenta', hex: '#de54be' },
  { name: 'rose', hex: '#e64e83' },
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
