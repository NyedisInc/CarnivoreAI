
export const MAX_SCRIPT_FILES = 50;

export const MAX_PREVIEW_FILES = 200;

export const MAX_PATH_CHARS = 120;

export const MAX_DIGEST_CHARS = 64;

export const CLIP_MARKER = '...';

export function clipChars(value: string | null | undefined, limit: number): string | null {
    if (typeof value !== 'string') return null;
    const points = [...value];
    if (points.length <= limit) return value;
    const marker = [...CLIP_MARKER];
    const keep = Math.max(0, limit - marker.length);
    return points.slice(0, keep).join('') + CLIP_MARKER;
}

export function boundedPath(file: { path?: string | null } | null | undefined): string {
    if (!file) return '';
    return clipChars(file.path, MAX_PATH_CHARS) ?? '';
}

export function boundedList<T>(
    items: readonly T[] | null | undefined,
    limit: number,
): { shown: T[]; hidden: number } {
    const all = Array.isArray(items) ? items : [];
    if (all.length <= limit) return { shown: [...all], hidden: 0 };
    return { shown: all.slice(0, limit), hidden: all.length - limit };
}
