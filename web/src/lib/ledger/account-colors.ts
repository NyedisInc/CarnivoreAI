
export interface AccountColor {
    hex: string;
    name: string;
}

export const STATUS_HUES: readonly number[] = Object.freeze([142, 45, 201, 0]);

export const ACCOUNT_COLORS: readonly AccountColor[] = Object.freeze([
    { hex: '#a3e635', name: 'lime' },
    { hex: '#2dd4bf', name: 'teal' },
    { hex: '#818cf8', name: 'indigo' },
    { hex: '#a78bfa', name: 'violet' },
    { hex: '#c084fc', name: 'purple' },
    { hex: '#e879f9', name: 'orchid' },
    { hex: '#ef5fd8', name: 'magenta' },
    { hex: '#f472b6', name: 'pink' },
    { hex: '#beed70', name: 'lime_soft' },
    { hex: '#62e1d1', name: 'teal_soft' },
    { hex: '#bfc5fc', name: 'indigo_soft' },
    { hex: '#d2c4fc', name: 'violet_soft' },
    { hex: '#e0c2ff', name: 'purple_soft' },
    { hex: '#f3b8fc', name: 'orchid_soft' },
    { hex: '#f69ae7', name: 'magenta_soft' },
    { hex: '#f9b0d6', name: 'pink_soft' },
    { hex: '#78b316', name: 'lime_deep' },
    { hex: '#219788', name: 'teal_deep' },
    { hex: '#3244f6', name: 'indigo_deep' },
    { hex: '#6c3df7', name: 'violet_deep' },
    { hex: '#9734fa', name: 'purple_deep' },
    { hex: '#db2bf6', name: 'orchid_deep' },
    { hex: '#e517c4', name: 'magenta_deep' },
    { hex: '#ee268f', name: 'pink_deep' },
] as const);

export const SWATCHES_PER_ROW = 8;

export const CUSTOM_COLOR_KEY = 'ledger.color.custom';

const HEX_SHAPE = /^#[0-9a-f]{6}$/;

export function hueOf(hex: string): number | null {
    if (typeof hex !== 'string' || !HEX_SHAPE.test(hex)) return null;
    const red = parseInt(hex.slice(1, 3), 16) / 255;
    const green = parseInt(hex.slice(3, 5), 16) / 255;
    const blue = parseInt(hex.slice(5, 7), 16) / 255;
    const max = Math.max(red, green, blue);
    const min = Math.min(red, green, blue);
    const span = max - min;
    if (span === 0) return null;
    let hue: number;
    if (max === red) hue = ((green - blue) / span) % 6;
    else if (max === green) hue = (blue - red) / span + 2;
    else hue = (red - green) / span + 4;
    hue = Math.round(hue * 60);
    return ((hue % 360) + 360) % 360;
}

export function lightnessOf(hex: string | null | undefined): number | null {
    if (typeof hex !== 'string' || !HEX_SHAPE.test(hex)) return null;
    const red = parseInt(hex.slice(1, 3), 16) / 255;
    const green = parseInt(hex.slice(3, 5), 16) / 255;
    const blue = parseInt(hex.slice(5, 7), 16) / 255;
    return (Math.max(red, green, blue) + Math.min(red, green, blue)) / 2;
}

export function hueDistance(left: number, right: number): number {
    const raw = Math.abs(left - right) % 360;
    return raw > 180 ? 360 - raw : raw;
}

export function isAccountColor(hex: string | null | undefined): boolean {
    if (typeof hex !== 'string') return false;
    return ACCOUNT_COLORS.some((swatch) => swatch.hex === hex);
}

export function isStorableColor(hex: string | null | undefined): boolean {
    if (typeof hex !== 'string') return false;
    return HEX_SHAPE.test(hex);
}

export function normaliseColorInput(value: string | null | undefined): string | null {
    if (typeof value !== 'string') return null;
    const lowered = value.trim().toLowerCase();
    return isStorableColor(lowered) ? lowered : null;
}

export function swatchLabelKey(hex: string | null | undefined): string {
    const swatch =
        typeof hex === 'string' ? ACCOUNT_COLORS.find((entry) => entry.hex === hex) : undefined;
    return swatch ? `ledger.color.${swatch.name}` : CUSTOM_COLOR_KEY;
}
