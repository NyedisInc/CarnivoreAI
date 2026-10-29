
export type Palette = 'carnivore' | 'oblivion';

export function hueOf(value: string | null | undefined): number | null {
    const v = (value ?? '').trim().toLowerCase();
    let r: number;
    let g: number;
    let b: number;
    const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})([0-9a-f]{2})?$/.exec(v);
    const fn = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/.exec(v);
    if (hex) {
        const h = (hex[1] ?? '').length === 3 ? (hex[1] ?? '').replace(/./g, (c) => c + c) : (hex[1] ?? '');
        r = parseInt(h.slice(0, 2), 16);
        g = parseInt(h.slice(2, 4), 16);
        b = parseInt(h.slice(4, 6), 16);
    } else if (fn) {
        r = +fn[1]!;
        g = +fn[2]!;
        b = +fn[3]!;
    } else {
        return null;
    }
    const max = Math.max(r, g, b);
    const d = max - Math.min(r, g, b);
    if (d === 0) return null;
    const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return (h * 60 + 360) % 360;
}

export function paletteForAccent(accent: string | null | undefined): Palette {
    const hue = hueOf(accent);
    return hue != null && hue >= 80 && hue <= 165 ? 'oblivion' : 'carnivore';
}

export function activePalette(): Palette {
    if (typeof document === 'undefined') return 'carnivore';
    return paletteForAccent(getComputedStyle(document.documentElement).getPropertyValue('--color-accent'));
}
