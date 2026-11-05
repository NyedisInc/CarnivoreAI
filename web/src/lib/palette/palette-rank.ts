import { insertRankedSearchResult, scoreQueryMatch, type RankedSearchResult } from './search-ranking';

export interface Rankable {
    id: string;
    title: string;
}

const TIER = 1_000_000;
const UNLEARNED = 100_000;
const TYPO_TIER = 5;
export const RANK_LIMIT = 50;
export const HALF_LIFE_MS = 14 * 24 * 3600 * 1000;
export const OPEN_DEDUPE_MS = 10 * 60 * 1000;
export const BOOST_CAP = 2.5;
export const MEMORY_CAP = 500;
const QUERIES_KEPT = 3;
const QUERY_CHARS = 32;
const OPENS_KEPT = 20;
const STORE_KEY = 'carnivore.palette.picks';

export interface PickMemory {
    queries: string[];
    opens: number[];
}

export type PickStore = Record<string, PickMemory>;

export function initials(title: string): string {
    const words = title.replace(/([a-z])([A-Z])/g, '$1 $2').split(/[\s\-_/.:]+/).filter(Boolean);
    return words.map((w) => w[0]!.toLowerCase()).join('');
}

function oneEdit(a: string, b: string): boolean {
    if (a === b) return true;
    if (Math.abs(a.length - b.length) > 1) return false;
    let i = 0;
    while (i < a.length && i < b.length && a[i] === b[i]) i += 1;
    if (a.length === b.length) {
        if (a.slice(i + 1) === b.slice(i + 1)) return true;
        return a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2);
    }
    return a.length > b.length ? a.slice(i + 1) === b.slice(i) : a.slice(i) === b.slice(i + 1);
}

export function matchTier(title: string, query: string, titleInitials: string): [number, number] | null {
    const s = scoreQueryMatch({ value: title, query, exactBase: 0, prefixBase: TIER, boundaryBase: 2 * TIER, includesBase: 3 * TIER, fuzzyBase: 4 * TIER });
    const byInitials = query.length >= 2 && titleInitials.startsWith(query) ? 2 * TIER + titleInitials.length - query.length : null;
    const best = s === null ? byInitials : byInitials === null ? s : Math.min(s, byInitials);
    if (best !== null) return [Math.floor(best / TIER), best % TIER];
    if (query.length < 3) return null;
    const words = title.split(/[\s\-_/.:]+/);
    for (const w of words) {
        if (oneEdit(w.slice(0, query.length), query) || oneEdit(w.slice(0, query.length + 1), query) || oneEdit(w.slice(0, query.length - 1), query)) {
            return [TYPO_TIER, Math.min(64, title.length)];
        }
    }
    return null;
}

export function frecency(opens: readonly number[], now: number): number {
    let sum = 0;
    for (const at of opens) sum += Math.pow(0.5, Math.max(0, now - at) / HALF_LIFE_MS);
    return sum;
}

export function boost(opens: readonly number[] | undefined, now: number): number {
    return Math.min(BOOST_CAP, 1 + (opens ? frecency(opens, now) * 0.5 : 0));
}

const folds = new WeakMap<Rankable, { title: string; initials: string }>();
function fold(item: Rankable): { title: string; initials: string } {
    let f = folds.get(item);
    if (!f || f.title.length !== item.title.length) {
        f = { title: item.title.toLowerCase(), initials: initials(item.title) };
        folds.set(item, f);
    }
    return f;
}

function learned(memory: PickMemory | undefined, query: string): boolean {
    return !!memory && memory.queries.some((q) => q.startsWith(query));
}

export function scoreItem(item: Rankable, query: string, memory: PickMemory | undefined, now: number): { tier: number; score: number } | null {
    const folded = fold(item);
    const hit = matchTier(folded.title, query, folded.initials);
    if (!hit) return null;
    const [tier, penalty] = hit;
    const inTier = Math.min(UNLEARNED - 1, Math.round(((penalty + 1) / boost(memory?.opens, now)) * 100));
    return { tier, score: tier * TIER + (learned(memory, query) ? 0 : UNLEARNED) + inTier };
}

function tieBreaker(item: Rankable): string {
    return `${String(item.title.length).padStart(4, '0')}\u0000${item.id}`;
}

export interface Ranker<T extends Rankable> {
    rank(items: readonly T[], query: string): T[];
}

export function createRanker<T extends Rankable>(memory: () => PickStore, now: () => number = Date.now): Ranker<T> {
    let lastItems: readonly T[] | null = null;
    let lastQuery = '';
    let lastMatched: T[] = [];
    return {
        rank(items, rawQuery) {
            const query = rawQuery.trim().toLowerCase();
            if (!query) return [];
            const narrowing = lastItems === items && lastQuery && query.startsWith(lastQuery);
            const pool = narrowing ? lastMatched : items;
            const store = memory();
            const at = now();
            const exact: RankedSearchResult<T>[] = [];
            const typos: RankedSearchResult<T>[] = [];
            const matched: T[] = [];
            for (const item of pool) {
                const s = scoreItem(item, query, store[item.id], at);
                if (!s) continue;
                matched.push(item);
                insertRankedSearchResult(s.tier === TYPO_TIER ? typos : exact, { item, score: s.score, tieBreaker: tieBreaker(item) }, RANK_LIMIT);
            }
            lastItems = items;
            lastQuery = query;
            lastMatched = matched;
            return (exact.length ? exact : typos).map((r) => r.item);
        },
    };
}

export function notePick(store: PickStore, id: string, query: string, now: number): void {
    const m = store[id] ?? { queries: [], opens: [] };
    const q = query.trim().toLowerCase().slice(0, QUERY_CHARS);
    if (q) m.queries = [q, ...m.queries.filter((x) => x !== q)].slice(0, QUERIES_KEPT);
    const last = m.opens[m.opens.length - 1];
    if (last === undefined || now - last >= OPEN_DEDUPE_MS) m.opens = [...m.opens, now].slice(-OPENS_KEPT);
    store[id] = m;
}

export function prunePicks(store: PickStore, live: ReadonlySet<string>): PickStore {
    const kept = Object.entries(store).filter(([id]) => live.has(id));
    kept.sort((a, b) => (b[1].opens[b[1].opens.length - 1] ?? 0) - (a[1].opens[a[1].opens.length - 1] ?? 0));
    return Object.fromEntries(kept.slice(0, MEMORY_CAP));
}

export function readPicks(): PickStore {
    try {
        const raw = globalThis.localStorage?.getItem(STORE_KEY);
        const parsed: unknown = raw ? JSON.parse(raw) : {};
        return parsed && typeof parsed === 'object' ? parsed as PickStore : {};
    } catch (err) {
        console.warn('palette: picks unreadable', err);
        return {};
    }
}

export function writePicks(store: PickStore): void {
    try {
        globalThis.localStorage?.setItem(STORE_KEY, JSON.stringify(store));
    } catch (err) {
        console.warn('palette: picks not saved', err);
    }
}
