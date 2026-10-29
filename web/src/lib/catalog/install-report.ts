import type { ItemInstalls } from './types';

export type InstallsShape = 'unavailable' | 'none' | 'counted';

export interface InstallsView {
    shape: InstallsShape;
    count: number | null;
}

function countOf(value: unknown): number | null {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null;
    if (value < 0) return null;
    return Math.trunc(value);
}

export function installsView(body: ItemInstalls | null | undefined): InstallsView {
    if (!body || typeof body !== 'object') {
        return { shape: 'unavailable', count: null };
    }
    const count = countOf(body.count);
    if (count === null) return { shape: 'unavailable', count: null };
    return { shape: count === 0 ? 'none' : 'counted', count };
}
