
export function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
    const hue = ((Number.isFinite(h) ? h : 0) % 360 + 360) % 360;
    const sat = Math.max(0, Math.min(1, Number.isFinite(s) ? s : 0));
    const val = Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));
    const f = (n: number): number => {
        const k = (n + hue / 60) % 6;
        return Math.round(255 * (val - val * sat * Math.max(0, Math.min(k, 4 - k, 1))));
    };
    return [f(5), f(3), f(1)];
}

export function rgbToHsv(r: number, g: number, b: number, keepHue = 0): [number, number, number] {
    const norm = (n: number): number => Math.max(0, Math.min(255, Number.isFinite(n) ? n : 0)) / 255;
    const [R, G, B] = [norm(r), norm(g), norm(b)];
    const max = Math.max(R, G, B);
    const d = max - Math.min(R, G, B);
    if (d === 0) return [keepHue, 0, max];
    let h = max === R ? ((G - B) / d) % 6 : max === G ? (B - R) / d + 2 : (R - G) / d + 4;
    h = (h * 60 + 360) % 360;
    return [h, d / max, max];
}
