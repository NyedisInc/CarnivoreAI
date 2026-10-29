import type { CatalogHost } from './catalog';
import { installsView } from './install-report';
import { displayKind } from './kind-display';
import type { CatalogItem } from './types';

const KIND_ORDER = ['skill', 'theme', 'mod', 'plugin', 'loadout'];

export interface KindCount {
    readonly kind: string;
    readonly count: number;
}

export function kindCounts(items: readonly CatalogItem[]): KindCount[] {
    const tally = new Map<string, number>();
    for (const item of items) {
        const kind = displayKind(item?.kind);
        if (kind) tally.set(kind, (tally.get(kind) ?? 0) + 1);
    }
    const rank = (kind: string): number => (KIND_ORDER.includes(kind) ? KIND_ORDER.indexOf(kind) : KIND_ORDER.length);
    return [...tally]
        .map(([kind, count]) => ({ kind, count }))
        .sort((a, b) => rank(a.kind) - rank(b.kind) || a.kind.localeCompare(b.kind));
}

/* first published */
export function newestItems(items: readonly CatalogItem[], limit = 5): CatalogItem[] {
    return items
        .filter((item) => typeof item?.first_published_at === 'string' && item.first_published_at)
        .sort((a, b) => (a.first_published_at! < b.first_published_at! ? 1 : a.first_published_at! > b.first_published_at! ? -1 : 0))
        .slice(0, limit);
}

export interface Downloaded {
    readonly item: CatalogItem;
    readonly count: number;
}

export function mostDownloaded(items: readonly CatalogItem[], installs: ReadonlyMap<string, number>, limit = 5): Downloaded[] {
    const ranked = items
        .flatMap((item) => (item?.id && installs.has(item.id) ? [{ item, count: installs.get(item.id)! }] : []))
        .sort((a, b) => b.count - a.count);
    return ranked.length > 0 && ranked[0].count > 0 ? ranked.slice(0, limit) : [];
}

export async function loadInstallCounts(host: CatalogHost, ids: readonly string[]): Promise<Map<string, number>> {
    const counts = new Map<string, number>();
    if (ids.length === 0) return counts;
    try {
        const answer = await host.installCounts(ids);
        for (const id of ids) {
            const view = installsView(answer?.items?.[id]);
            if (view.count !== null) counts.set(id, view.count);
        }
    } catch {
    }
    return counts;
}
