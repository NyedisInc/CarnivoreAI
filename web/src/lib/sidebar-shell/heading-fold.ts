import { t } from '../i18n/index.svelte';
import { announce, repaintDrawerRows } from './interaction-globals';
import { isCollapsed, setCollapsedMany, toggleCollapsed } from '../drawer/store';
import {
    COMPANIES_FOLD_KEY, GROUPS_FOLD_KEY, LAYOUT_FOLD_KEY, PACK_FOLD_KEY, ROGUE_FOLD_KEY, isSpawnedFoldKey,
} from '../drawer/store-keys';
import { BAND_PROJECT_PREFIX, groupByUuid, groupUuidOf } from '../drawer/group-store';
import { companySource } from './company-source.svelte';
import { cascadeKeysFor, liveCascadeWorld } from './cascade-keys';

const LAYOUT_ITEM_PREFIX = 'layout:';

const RESERVED_BAND_LABELS: Readonly<Record<string, string>> = {
    [COMPANIES_FOLD_KEY]: 'sidebar.companies.heading',
    [GROUPS_FOLD_KEY]: 'sidebar.groups.heading',
    [PACK_FOLD_KEY]: 'sidebar.pack.heading',
    pinned: 'sidebar.band.pinned',
    other: 'sidebar.band.other',
    [ROGUE_FOLD_KEY]: 'sidebar.band.rogue',
    [LAYOUT_FOLD_KEY]: 'sidebar.band.layouts',
    terminals: 'sidebar.band.terminals',
    browsers: 'sidebar.band.browsers',
    files: 'sidebar.band.files',
};

function bandLabel(key: string): string {
    if (key === 'c:orphaned') return t('sidebar.company.orphaned');
    if (isSpawnedFoldKey(key)) return t('sidebar.spawned.name');
    if (RESERVED_BAND_LABELS[key]) return t(RESERVED_BAND_LABELS[key]);
    if (key.indexOf(BAND_PROJECT_PREFIX) === 0) return companySource().projectNameOf?.(key.slice(BAND_PROJECT_PREFIX.length)) ?? key;
    const groupUuid = groupUuidOf(key);
    if (groupUuid) return groupByUuid(groupUuid)?.name || key;
    if (key.indexOf('c:') !== 0) return key;
    const id = Number(key.slice(2));
    return companySource().companies.find((c) => c.id === id)?.name ?? key;
}

export function toggleBandFold(key: string): boolean {
    if (!key) return false;
    const nowPresent = toggleCollapsed(key);
    repaintDrawerRows();
    const expandedWhenPresent = key.indexOf(LAYOUT_ITEM_PREFIX) === 0 || isSpawnedFoldKey(key);
    const folded = expandedWhenPresent ? !nowPresent : nowPresent;
    announce(t(folded ? 'sidebar.heading.fold.collapsed' : 'sidebar.heading.fold.expanded', { key: bandLabel(key) }));
    return true;
}

export function cascadeBandFold(key: string): boolean {
    if (!key) return false;
    const inverted = key.indexOf(LAYOUT_ITEM_PREFIX) === 0 || isSpawnedFoldKey(key);
    const foldedNow = inverted ? !isCollapsed(key) : isCollapsed(key);
    const fold = !foldedNow;
    const under = cascadeKeysFor(key, liveCascadeWorld());
    const own = inverted ? [] : [key];
    const ownInverted = inverted ? [key] : [];
    const folded = [...own, ...under.tree];
    const expanded = [...ownInverted, ...under.inverted];
    const add = fold ? folded : expanded;
    const remove = fold ? expanded : folded;
    setCollapsedMany(add, remove);
    repaintDrawerRows();
    announce(t(fold ? 'sidebar.heading.cascade.collapsed' : 'sidebar.heading.cascade.expanded', { key: bandLabel(key) }));
    return true;
}
