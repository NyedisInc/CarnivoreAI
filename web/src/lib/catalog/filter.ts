import type { CardView } from './card';
import { anyUpdate } from './installed-rows';
import type { InstalledItem } from './types';

export interface CatalogFilters {
    installed: boolean;
    available: boolean;
    updates: boolean;
    untrusted: boolean;
    scripts: boolean;
    publisher: string | null;
    kind: string | null;
    tags: readonly string[];
}

export const NO_FILTERS: CatalogFilters = {
    installed: false,
    available: false,
    updates: false,
    untrusted: false,
    scripts: false,
    publisher: null,
    kind: null,
    tags: [],
};

/* anything at all */
export function isNarrowed(filters: CatalogFilters, query: string): boolean {
    return (
        filters.installed ||
        filters.available ||
        filters.updates ||
        filters.untrusted ||
        filters.scripts ||
        filters.publisher !== null ||
        filters.kind !== null ||
        filters.tags.length > 0 ||
        query.trim() !== ''
    );
}

function fold(value: unknown): string {
    return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function haystack(card: CardView): string[] {
    const terms = [fold(card.headline), fold(card.name), fold(card.brief), fold(card.publisher)];
    for (const tag of card.tags || []) terms.push(fold(tag));
    return terms.filter((term) => term !== '');
}

export function matchesQuery(card: CardView, query: string): boolean {
    const words = fold(query).split(/\s+/).filter((word) => word !== '');
    if (words.length === 0) return true;
    const terms = haystack(card);
    return words.every((word) => terms.some((term) => term.includes(word)));
}

export function matchesFilters(
    card: CardView,
    filters: CatalogFilters,
    installed: Record<string, InstalledItem[]>,
): boolean {
    const rows = card.id ? installed[card.id] : undefined;
    if (filters.installed && !(rows && rows.length)) return false;
    if (filters.available && rows && rows.length) return false;
    if (filters.updates && !anyUpdate(rows)) return false;
    if (filters.untrusted && !card.untrusted) return false;
    if (filters.scripts && !card.marksScripts) return false;
    if (filters.publisher !== null && card.publisher !== filters.publisher) return false;
    if (filters.kind !== null && card.kind !== filters.kind) return false;
    if (filters.tags.length) {
        const tags = card.tags || [];
        for (const wanted of filters.tags) {
            if (!tags.includes(wanted)) return false;
        }
    }
    return true;
}

export function visibleCards(
    cards: readonly CardView[],
    filters: CatalogFilters,
    query: string,
    installed: Record<string, InstalledItem[]>,
): CardView[] {
    return cards.filter(
        (card) => matchesFilters(card, filters, installed) && matchesQuery(card, query),
    );
}

export function publishersOf(cards: readonly CardView[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const card of cards) {
        const publisher = card.publisher;
        if (!publisher || seen.has(publisher)) continue;
        seen.add(publisher);
        out.push(publisher);
    }
    return out;
}

export function kindsOf(cards: readonly CardView[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const card of cards) {
        const kind = card.kind;
        if (!kind || seen.has(kind)) continue;
        seen.add(kind);
        out.push(kind);
    }
    return out;
}

export const MAX_TAG_CHIPS = 40;

export function tagsOf(cards: readonly CardView[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const card of cards) {
        for (const tag of card.tags || []) {
            if (seen.has(tag)) continue;
            seen.add(tag);
            out.push(tag);
            if (out.length >= MAX_TAG_CHIPS) return out;
        }
    }
    return out;
}

export function updateCount(rows: readonly InstalledItem[] | null | undefined): number {
    if (!Array.isArray(rows)) return 0;
    let count = 0;
    for (const row of rows) {
        if (row && row.update_available === true) count += 1;
    }
    return count;
}
