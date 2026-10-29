
export const FAVORITE_COLORS = ['yellow', 'green', 'cyan', 'violet', 'coral'] as const;

export type FavoriteColor = (typeof FAVORITE_COLORS)[number];

export interface Favorite {
    command: string;
    description: string;
    color: FavoriteColor | null;
}

export interface FavoritesRow {
    favorites: Favorite[];
    defaulted: boolean;
}

export interface Rect {
    left: number;
    top: number;
    right: number;
    bottom: number;
}

export function isFavoriteColor(value: unknown): value is FavoriteColor {
    return typeof value === 'string' && (FAVORITE_COLORS as readonly string[]).includes(value);
}

export function swatchVar(color: FavoriteColor): string {
    return `var(--oc-${color})`;
}

export function rowFromPayload(payload: unknown): FavoritesRow {
    const body = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
    const details = Array.isArray(body.command_details) ? body.command_details : [];
    const favorites: Favorite[] = [];
    for (const raw of details) {
        if (!raw || typeof raw !== 'object') continue;
        const entry = raw as Record<string, unknown>;
        if (typeof entry.command !== 'string' || entry.command === '') continue;
        favorites.push({
            command: entry.command,
            description: typeof entry.description === 'string' ? entry.description : '',
            color: isFavoriteColor(entry.color) ? entry.color : null,
        });
    }
    return { favorites, defaulted: body.defaulted === true };
}

export function moveItem<T>(list: readonly T[], from: number, to: number): T[] {
    const out = list.slice();
    if (from < 0 || from >= out.length) return out;
    const target = Math.max(0, Math.min(out.length - 1, to));
    if (target === from) return out;
    const [item] = out.splice(from, 1);
    out.splice(target, 0, item as T);
    return out;
}

export function keyboardDelta(key: string, altKey: boolean): -1 | 0 | 1 {
    if (!altKey) return 0;
    if (key === 'ArrowLeft' || key === 'ArrowUp') return -1;
    if (key === 'ArrowRight' || key === 'ArrowDown') return 1;
    return 0;
}

export function indexAtPoint(rects: readonly Rect[], x: number, y: number): number {
    let best = -1;
    let bestDistance = Infinity;
    for (let i = 0; i < rects.length; i++) {
        const r = rects[i] as Rect;
        if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return i;
        const cx = (r.left + r.right) / 2;
        const cy = (r.top + r.bottom) / 2;
        const distance = (cx - x) ** 2 + (cy - y) ** 2;
        if (distance < bestDistance) {
            bestDistance = distance;
            best = i;
        }
    }
    return best;
}

export function sameOrder(a: readonly string[], b: readonly string[]): boolean {
    return a.length === b.length && a.every((value, i) => value === b[i]);
}
