import { latestVersion, type CardView } from './card';
import type { CatalogItem } from './types';

export const SORT_KEYS = ['featured', 'newest', 'oldest', 'name', 'updated', 'downloaded', 'index'] as const;
export type SortKey = (typeof SORT_KEYS)[number];

export const VISIBLE_SORT_KEYS = SORT_KEYS.filter((key) => key !== 'index');

export function sortCards(
    cards: readonly CardView[],
    key: SortKey,
    items: readonly CatalogItem[],
    installs: ReadonlyMap<string, number> = new Map(),
): CardView[] {
    const out = [...cards];
    if (key === 'index') return out;
    if (key === 'downloaded') {
        const pos = new Map(out.map((card, i) => [card, i] as const));
        const n = (card: CardView): number => (card.id ? (installs.get(card.id) ?? -1) : -1);
        return out.sort((a, b) => n(b) - n(a) || (pos.get(a) ?? 0) - (pos.get(b) ?? 0));
    }
    if (key === 'featured' || key === 'newest' || key === 'oldest') {
        const byId = new Map<string, CatalogItem>();
        for (const item of items) if (item?.id) byId.set(item.id, item);
        const rank = (card: CardView): number | null => {
            const r = card.id ? byId.get(card.id)?.featured_rank : null;
            return typeof r === 'number' && Number.isFinite(r) ? r : null;
        };
        const first = (card: CardView): string => {
            const at = card.id ? byId.get(card.id)?.first_published_at : null;
            return typeof at === 'string' ? at : '';
        };
        const pos = new Map(out.map((card, i) => [card, i] as const));
        const tie = (a: CardView, b: CardView): number => (pos.get(a) ?? 0) - (pos.get(b) ?? 0);
        return out.sort((a, b) => {
            if (key === 'featured') {
                const x = rank(a);
                const y = rank(b);
                if (x === y) return tie(a, b);
                if (x === null) return 1;
                if (y === null) return -1;
                return x - y;
            }
            const x = first(a);
            const y = first(b);
            if (x === y) return tie(a, b);
            if (!x) return 1;
            if (!y) return -1;
            return (x < y ? -1 : 1) * (key === 'newest' ? -1 : 1);
        });
    }
    if (key === 'name') {
        return out.sort((a, b) =>
            (a.headline ?? '').toLowerCase().localeCompare((b.headline ?? '').toLowerCase()),
        );
    }
    const stamp = new Map<string, string>();
    for (const item of items) {
        const at = latestVersion(item)?.published_at;
        if (item?.id && typeof at === 'string' && at) stamp.set(item.id, at);
    }
    const at = (card: CardView): string => (card.id ? (stamp.get(card.id) ?? '') : '');
    return out.sort((a, b) => {
        const x = at(a);
        const y = at(b);
        if (x === y) return 0;
        if (!x) return 1;
        if (!y) return -1;
        return x < y ? 1 : -1;
    });
}
