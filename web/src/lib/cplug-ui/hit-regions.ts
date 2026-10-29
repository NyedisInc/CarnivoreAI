
export interface Rect {
    x: number;
    y: number;
    w: number;
    h: number;
}

export const MAX_RECTS = 16;
export const MAX_SIDE = 640;

export function sanitizeRects(raw: unknown, viewport: { w: number; h: number }): Rect[] {
    if (!Array.isArray(raw)) return [];
    const out: Rect[] = [];
    for (const r of raw.slice(0, MAX_RECTS)) {
        if (typeof r !== 'object' || r === null) continue;
        const { x, y, w, h } = r as Record<string, unknown>;
        if (![x, y, w, h].every((n) => typeof n === 'number' && Number.isFinite(n))) continue;
        if ((w as number) <= 0 || (h as number) <= 0 || (w as number) > MAX_SIDE || (h as number) > MAX_SIDE) continue;
        const left = Math.max(0, x as number);
        const top = Math.max(0, y as number);
        const right = Math.min(viewport.w, (x as number) + (w as number));
        const bottom = Math.min(viewport.h, (y as number) + (h as number));
        if (right - left >= 1 && bottom - top >= 1) out.push({ x: left, y: top, w: right - left, h: bottom - top });
    }
    return out;
}

export function subtract(rect: Rect, hole: Rect): Rect[] {
    const ix1 = Math.max(rect.x, hole.x);
    const iy1 = Math.max(rect.y, hole.y);
    const ix2 = Math.min(rect.x + rect.w, hole.x + hole.w);
    const iy2 = Math.min(rect.y + rect.h, hole.y + hole.h);
    if (ix1 >= ix2 || iy1 >= iy2) return [rect];
    const pieces: Rect[] = [
        { x: rect.x, y: rect.y, w: rect.w, h: iy1 - rect.y },
        { x: rect.x, y: iy2, w: rect.w, h: rect.y + rect.h - iy2 },
        { x: rect.x, y: iy1, w: ix1 - rect.x, h: iy2 - iy1 },
        { x: ix2, y: iy1, w: rect.x + rect.w - ix2, h: iy2 - iy1 },
    ];
    return pieces.filter((p) => p.w >= 1 && p.h >= 1);
}

export function enabledRects(rects: readonly Rect[], excluded: readonly Rect[]): Rect[] {
    return excluded.reduce<Rect[]>((left, hole) => left.flatMap((r) => subtract(r, hole)), [...rects]);
}

export function clipPath(rects: readonly Rect[]): string {
    if (rects.length === 0) return "path('M0 0')";
    return `path('${rects.map((r) => `M${r.x} ${r.y}h${r.w}v${r.h}h${-r.w}z`).join('')}')`;
}

export function createTerminalWatch(read: () => Rect[], onChange: () => void): { look: () => void } {
    const key = (rects: Rect[]): string => rects.map((r) => `${Math.round(r.x)},${Math.round(r.y)},${Math.round(r.w)},${Math.round(r.h)}`).join('|');
    let last: string | null = null;
    return {
        look(): void {
            const now = key(read());
            const changed = last !== null && now !== last;
            last = now;
            if (changed) onChange();
        },
    };
}
