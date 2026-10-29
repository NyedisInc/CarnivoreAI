
export const DETAIL_WIDTH_KEY = 'carnivore.catalogDetail.width';

export const THEME_DETAIL_WIDTH = 380;

export const DETAIL_DEFAULT_WIDTH = 400;

export const DETAIL_WIDE_WIDTH = 440;

export const DETAIL_WIDE_CONTAINER = 1600;

export const DETAIL_MIN_WIDTH = 320;

export const DETAIL_MAX_WIDTH = 640;

export const LIST_MIN_WIDTH = 280;

export const DETAIL_KEY_STEP = 16;

export function clampDetailWidth(px: number, container: number): number {
    const room = container > 0 ? container - LIST_MIN_WIDTH : DETAIL_MAX_WIDTH;
    const cap = Math.max(DETAIL_MIN_WIDTH, Math.min(DETAIL_MAX_WIDTH, room));
    const wanted = Number.isFinite(px) ? px : DETAIL_DEFAULT_WIDTH;
    return Math.round(Math.min(Math.max(wanted, DETAIL_MIN_WIDTH), cap));
}

export function defaultDetailWidth(container = 0): number {
    return container >= DETAIL_WIDE_CONTAINER ? DETAIL_WIDE_WIDTH : DETAIL_DEFAULT_WIDTH;
}

export function readDetailWidth(container = 0): number {
    let raw: string | null = null;
    try {
        raw = window.localStorage.getItem(DETAIL_WIDTH_KEY);
    } catch {
        raw = null;
    }
    const parsed = raw === null ? NaN : Number(raw);
    return clampDetailWidth(Number.isFinite(parsed) && parsed > 0 ? parsed : defaultDetailWidth(container), container);
}

export function writeDetailWidth(px: number): void {
    try {
        window.localStorage.setItem(DETAIL_WIDTH_KEY, String(px));
    } catch {
    }
}
