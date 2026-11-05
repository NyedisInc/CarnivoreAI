
export const BADGE_ORDER = ['progress', 'ports', 'pr'] as const;
export type BadgeKind = (typeof BADGE_ORDER)[number];

export const SLOT_MAX_ITEMS = 5;

export interface BadgeItem {
    kind: BadgeKind;
    key: string;
    text: string;
    title: string;
    tone?: string;
    pct?: number;
    activate?: (event: MouseEvent) => void;
}

export interface BadgeSlotPlan {
    items: BadgeItem[];
    more: number;
    moreTitle: string;
}

export type BadgeSource = (row: Record<string, unknown>) => BadgeItem[];

interface Registered { source: BadgeSource; max: number }

const sources = new Map<BadgeKind, Registered>();

export function registerBadgeSource(kind: BadgeKind, source: BadgeSource, max: number = SLOT_MAX_ITEMS): () => void {
    const entry = { source, max };
    sources.set(kind, entry);
    return () => {
        if (sources.get(kind) === entry) sources.delete(kind);
    };
}

/* there is nothing */
export function badgeSlotPlan(row: Record<string, unknown> | null | undefined): BadgeSlotPlan | null {
    if (!row || sources.size === 0) return null;
    const items: BadgeItem[] = [];
    const folded: BadgeItem[] = [];
    for (const kind of BADGE_ORDER) {
        const entry = sources.get(kind);
        if (!entry) continue;
        let got: BadgeItem[];
        try {
            got = entry.source(row) ?? [];
        } catch (err) {
            console.warn('badge source failed', kind, err);
            got = [];
        }
        got.forEach((item, i) => (i < entry.max ? items : folded).push(item));
    }
    while (items.length > SLOT_MAX_ITEMS) folded.unshift(items.pop() as BadgeItem);
    if (items.length === 0 && folded.length === 0) return null;
    return { items, more: folded.length, moreTitle: folded.map((b) => b.title).join('\n') };
}
