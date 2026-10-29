
import type { ThemeManifest } from '../../opscenter/api';

export const THEME_FILTERS = ['all', 'favorites', 'builtin', 'user', 'ascii'] as const;

export type ThemeFilter = (typeof THEME_FILTERS)[number];

export function isAscii(manifest: ThemeManifest): boolean {
    return manifest.cssVars?.['--ascii-display'] === 'block';
}

export function sortThemes(manifests: readonly ThemeManifest[]): ThemeManifest[] {
    return [...manifests].sort((a, b) => {
        const builtin = Number(b.source === 'builtin') - Number(a.source === 'builtin');
        return builtin || a.name.localeCompare(b.name);
    });
}

export function passesFilter(manifest: ThemeManifest, filter: ThemeFilter, favorites: readonly string[]): boolean {
    if (filter === 'favorites') return favorites.includes(manifest.id);
    if (filter === 'builtin') return manifest.source === 'builtin';
    if (filter === 'user') return manifest.source !== 'builtin';
    if (filter === 'ascii') return isAscii(manifest);
    return true;
}

export function matchesQuery(manifest: ThemeManifest, query: string): boolean {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    const haystack = [manifest.name, manifest.id, manifest.author ?? '', manifest.description].join(' ').toLowerCase();
    return words.every((word) => haystack.includes(word));
}

export function visibleThemes(
    manifests: readonly ThemeManifest[] | null,
    filter: ThemeFilter,
    query: string,
    favorites: readonly string[],
): ThemeManifest[] {
    if (!manifests) return [];
    return sortThemes(manifests).filter((m) => passesFilter(m, filter, favorites) && matchesQuery(m, query));
}

export function filterCounts(
    manifests: readonly ThemeManifest[] | null,
    favorites: readonly string[],
): Record<ThemeFilter, number> {
    const list = manifests ?? [];
    const counts = {} as Record<ThemeFilter, number>;
    for (const filter of THEME_FILTERS) counts[filter] = list.filter((m) => passesFilter(m, filter, favorites)).length;
    return counts;
}
