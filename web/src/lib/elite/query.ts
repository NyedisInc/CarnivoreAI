/* the downloaded sort */
import type { CardView } from '../catalog/card';
import { matchesFilters, matchesQuery, NO_FILTERS, type CatalogFilters } from '../catalog/filter';
import { sortCards, type SortKey } from '../catalog/sort';
import type { CatalogItem, InstalledItem } from '../catalog/types';

export type StateKey = 'any' | 'installed' | 'available' | 'updates';

export type ViewKey = 'new' | 'top' | null;

export interface BoardQuery {
    kind: string;
    state: StateKey;
    q: string;
    sort: SortKey;
    view: ViewKey;
}

export const START: BoardQuery = { kind: 'all', state: 'any', q: '', sort: 'newest', view: null };

export const TOP_COUNT = 10;
export const FRESH_COUNT = 5;

export const FILE_KEYS: Readonly<Record<string, string>> = { a: 'all', s: 'skill', t: 'theme', m: 'mod', p: 'plugin' };
export const STATE_KEYS: Readonly<Record<string, StateKey>> = { i: 'installed', v: 'available', u: 'updates' };
export const SORT_KEYS: Readonly<Record<string, SortKey>> = { f: 'featured', w: 'newest', o: 'oldest', e: 'name', d: 'downloaded', c: 'updated' };

export interface Source {
    cards: readonly CardView[];
    items: readonly CatalogItem[];
    installed: Record<string, InstalledItem[]>;
    installs: ReadonlyMap<string, number>;
    fresh: ReadonlySet<string>;
}

export interface Census {
    total: number;
    files: Record<string, number>;
    state: Record<string, number>;
}

function filtersFor(kind: string, state: StateKey): CatalogFilters {
    return { ...NO_FILTERS, kind: kind === 'all' ? null : kind, installed: state === 'installed', available: state === 'available', updates: state === 'updates' };
}

function narrow(src: Source, kind: string, state: StateKey, q: string): CardView[] {
    const f = filtersFor(kind, state);
    return src.cards.filter((c) => matchesFilters(c, f, src.installed) && matchesQuery(c, q));
}

export function listFor(src: Source, q: BoardQuery): CardView[] {
    const rows = narrow(src, q.kind, q.state, q.q);
    if (q.view === 'top') {
        const measured = rows.filter((c) => c.id !== null && src.installs.has(c.id));
        return sortCards(measured, 'downloaded', src.items, src.installs).slice(0, TOP_COUNT);
    }
    const kept = q.view === 'new' ? rows.filter((c) => c.id !== null && src.fresh.has(c.id)) : rows;
    return sortCards(kept, q.sort, src.items, src.installs);
}

export function censusOf(src: Source, q: BoardQuery): Census {
    const files: Record<string, number> = {};
    for (const [key, kind] of Object.entries(FILE_KEYS)) files[key] = narrow(src, kind, q.state, q.q).length;
    const state: Record<string, number> = {};
    for (const [key, st] of Object.entries(STATE_KEYS)) state[key] = narrow(src, q.kind, st, q.q).length;
    state.n = narrow(src, q.kind, 'any', q.q).filter((c) => c.id !== null && src.fresh.has(c.id)).length;
    return { total: src.cards.length, files, state };
}

export function applyKey(q: BoardQuery, key: string): BoardQuery | null {
    const out = { ...q, view: null as ViewKey };
    if (key in FILE_KEYS) return { ...out, kind: FILE_KEYS[key]!, state: 'any', q: '' };
    if (key in STATE_KEYS) return { ...out, state: q.state === STATE_KEYS[key] ? 'any' : STATE_KEYS[key]!, q: '' };
    if (key in SORT_KEYS) return { ...out, sort: SORT_KEYS[key]! };
    if (key === 'n') return q.view === 'new' ? { ...out, state: 'any', q: '' } : { ...out, kind: 'all', state: 'any', q: '', view: 'new' };
    if (key === 'l') return q.view === 'top' ? { ...START } : { ...out, sort: 'downloaded', kind: 'all', state: 'any', q: '', view: 'top' };
    return null;
}

export function searchQuery(q: BoardQuery, text: string): BoardQuery {
    return { ...q, kind: 'all', state: 'any', q: text.replace(/^\//, '').trim(), view: null };
}

export interface ActiveKeys {
    files: string | null;
    state: string | null;
    sort: string | null;
    board: string | null;
}

export function activeKeys(q: BoardQuery): ActiveKeys {
    const key = (map: Readonly<Record<string, string>>, value: string): string | null => Object.keys(map).find((k) => map[k] === value) ?? null;
    return {
        files: q.q ? null : key(FILE_KEYS, q.kind),
        state: q.view === 'new' ? 'n' : key(STATE_KEYS, q.state),
        sort: key(SORT_KEYS, q.sort),
        board: q.view === 'top' ? 'l' : null,
    };
}

export function areaNo(q: BoardQuery): number {
    const kinds = ['all', 'skill', 'theme', 'mod', 'plugin'];
    return q.q ? 9 : q.state === 'installed' ? 6 : q.state === 'updates' ? 7 : kinds.indexOf(q.kind) + 1;
}

export function nextSort(sort: SortKey): SortKey {
    const cycle: SortKey[] = ['newest', 'oldest', 'name', 'downloaded', 'featured', 'updated'];
    return cycle[(cycle.indexOf(sort) + 1) % cycle.length]!;
}
