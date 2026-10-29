import { previewPalette, type PreviewPalette } from '../themes-page/preview-palette';
import type { ThemePaletteEntry, ThemePalettesResponse } from './types';

export function paletteOf(id: string, entry: ThemePaletteEntry): PreviewPalette {
    const palette = previewPalette({
        id,
        name: id,
        description: '',
        author: null,
        version: entry.version,
        cssVars: { ...(entry.cssVars ?? {}), '--ascii-display': entry.ascii ? 'block' : '' },
        xterm: { ...(entry.xterm ?? {}) },
        source: 'user',
    });
    return { ...palette, artwork: null, background: null };
}

export function palettesFrom(response: ThemePalettesResponse | null | undefined): ReadonlyMap<string, PreviewPalette> {
    const out = new Map<string, PreviewPalette>();
    const items = response?.items;
    if (!items || typeof items !== 'object') return out;
    for (const [id, entry] of Object.entries(items)) {
        if (entry && typeof entry === 'object') out.set(id, paletteOf(id, entry));
    }
    return out;
}

export function pendingOf(response: ThemePalettesResponse | null | undefined): string[] {
    return Array.isArray(response?.pending) ? response!.pending : [];
}
