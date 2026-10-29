/* is not installed */
import type { CardView } from '../catalog/card';
import { latestVersion } from '../catalog/card';
import type { CatalogItem, InstalledItem } from '../catalog/types';

export interface TaggedRow {
    id: string;
    name: string;
    size: number;
    update: boolean;
    installed: boolean;
}

export function taggedRows(tagged: ReadonlySet<string>, listing: readonly CatalogItem[], cards: readonly CardView[], installed: Record<string, InstalledItem[]>): TaggedRow[] {
    const byId = new Map(cards.map((c) => [c.id ?? '', c]));
    const items = new Map(listing.map((i) => [String(i.id ?? ''), i]));
    const rows: TaggedRow[] = [];
    for (const id of tagged) {
        const item = items.get(id);
        if (!item) continue;
        const held = installed[id] ?? [];
        rows.push({
            id,
            name: byId.get(id)?.headline ?? id,
            size: Number(latestVersion(item)?.size ?? 0) || 0,
            update: held.some((r) => r.update_available === true),
            installed: held.length > 0,
        });
    }
    return rows;
}

export function batchTake(mode: 'd' | 'u', rows: readonly TaggedRow[]): TaggedRow[] {
    return rows.filter((r) => (mode === 'u' ? r.update : !r.installed || r.update));
}
