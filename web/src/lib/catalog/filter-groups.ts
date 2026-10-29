import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
import { kindLabel } from '../../../../client/js/labels/catalog-kind.js';
import type { Translate } from '../sessions/types';
import type { CatalogFilters } from './filter';
import { VISIBLE_SORT_KEYS, type SortKey } from './sort';

export type StateGroup = 'any' | 'installed' | 'available' | 'updates';

const STATE_FLAGS = ['installed', 'available', 'updates'] as const;

export function stateOf(filters: CatalogFilters): StateGroup {
    return STATE_FLAGS.find((flag) => filters[flag]) ?? 'any';
}

export function withState(filters: CatalogFilters, next: StateGroup): CatalogFilters {
    return { ...filters, installed: next === 'installed', available: next === 'available', updates: next === 'updates' };
}

export function pressOrClear<T extends string>(current: T | 'any', pressed: T): T | 'any' {
    return current === pressed ? 'any' : pressed;
}

export interface PickerOption {
    readonly value: string;
    readonly label: string;
}

const SORT_LABELS: Partial<Record<SortKey, string>> = {
    featured: BROWSE_KEYS.sortFeatured,
    newest: BROWSE_KEYS.sortNewest,
    oldest: BROWSE_KEYS.sortOldest,
    name: BROWSE_KEYS.sortName,
    updated: BROWSE_KEYS.sortUpdated,
    downloaded: BROWSE_KEYS.sortDownloaded,
};

export function sortOptions(t: Translate): PickerOption[] {
    return VISIBLE_SORT_KEYS.map((key) => ({ value: key, label: t(SORT_LABELS[key] ?? '') }));
}

const KIND_CHIPS: readonly (readonly [string, string])[] = [
    ['skill', BROWSE_KEYS.kindChipSkill],
    ['theme', BROWSE_KEYS.kindChipTheme],
    ['mod', BROWSE_KEYS.kindChipMod],
    ['plugin', BROWSE_KEYS.kindChipPlugin],
    ['loadout', BROWSE_KEYS.kindChipLoadout],
];

export function kindChipsFor(kinds: readonly string[], selected: string | null, t: Translate): { kind: string; label: string }[] {
    const present = new Set(kinds);
    if (selected) present.add(selected);
    if (present.size < 2 && !selected) return [];
    const known = new Set(KIND_CHIPS.map(([kind]) => kind));
    return [
        ...KIND_CHIPS.filter(([kind]) => present.has(kind)).map(([kind, key]) => ({ kind, label: t(key) })),
        ...[...present].filter((kind) => !known.has(kind)).map((kind) => ({ kind, label: kindLabel(kind, t) ?? kind })),
    ];
}

export const STATE_SEGMENTS: readonly (readonly [StateGroup, string])[] = [
    ['installed', 'skill.filter.installed'],
    ['available', BROWSE_KEYS.filterAvailable],
    ['updates', 'warez.state.updates'],
];

export function stateTip(value: string, t: Translate): string {
    return t({ installed: BROWSE_KEYS.filterInstalledSomewhere, available: BROWSE_KEYS.stateTipAvailable, updates: BROWSE_KEYS.stateTipUpdates }[value] ?? '');
}
