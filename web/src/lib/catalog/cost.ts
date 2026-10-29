import type { CatalogItem, InstalledItem } from './types';

export interface CostView {
    desc: number | null;
    body: number | null;
}

function count(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value) : null;
}

export function costView(item: CatalogItem | null): CostView | null {
    const cost = item && item.cost;
    if (!cost || typeof cost !== 'object') return null;
    const view = { desc: count(cost.desc_tokens), body: count(cost.body_tokens) };
    return view.desc === null && view.body === null ? null : view;
}

export function installedDescTotal(
    items: readonly CatalogItem[],
    installed: Record<string, InstalledItem[]>,
): number | null {
    let total = 0;
    let counted = 0;
    for (const item of items) {
        const id = item && item.id;
        if (!id || !installed[id] || !installed[id].length) continue;
        const desc = costView(item)?.desc ?? null;
        if (desc === null) continue;
        total += desc;
        counted += 1;
    }
    return counted ? total : null;
}
