import * as G from './group-store';
import * as S from './store';
import { isBandOrderKey } from './store-keys';

export interface ArrangedRow {
    name: string;
    is_pinned?: boolean;
    band_key?: string;
    [field: string]: unknown;
}

export interface MoveResult {
    order: string[];
    crossed: boolean;
    pinned: boolean;
}

export function groupStore(): typeof G | null {
    return G.isUsable() ? G : null;
}

export function arrange<T extends ArrangedRow>(rows: readonly T[]): { rows: T[]; missing: string[] } {
    const list = Array.isArray(rows) ? rows.slice() : [];
    const byName = new Map<string, T>();
    for (const row of list) if (row && typeof row.name === 'string') byName.set(row.name, row);

    const st = S.current();
    const known = new Set(st.order);
    const ordered: T[] = [];
    for (const name of st.order) {
        const row = byName.get(name);
        if (row) ordered.push(row);
    }
    const G0 = groupStore();
    const fresh = list.filter((row) => !known.has(row.name));
    const rankOf = (row: T): number => {
        const r = G0 ? G0.memberRank(row.name) : null;
        return r === null || r === undefined ? Infinity : r;
    };
    fresh.map((row, i) => ({ row, i, r: rankOf(row) }))
        .sort((a, b) => (a.r - b.r) || (a.i - b.i))
        .forEach((x) => ordered.push(x.row));

    const Gs = groupStore();
    const keys = Gs ? Gs.bandOrder() : ['pinned', 'other'];
    const buckets = new Map<string, T[]>(keys.map((k) => [k, []]));
    for (const row of ordered) {
        row.is_pinned = S.isPinned(row.name);
        row.band_key = Gs ? Gs.bandOf(row.name, row.is_pinned) : (row.is_pinned ? 'pinned' : 'other');
        if (!buckets.has(row.band_key)) row.band_key = 'other';
        (buckets.get(row.band_key) as T[]).push(row);
    }
    let out: T[] = [];
    for (const key of keys) out = out.concat(buckets.get(key) as T[]);

    const remembered = S.dedupe(st.order.concat(st.pinned));
    const missing = remembered.filter((n) => !byName.has(n));
    return { rows: out, missing };
}

export function mergeInto(base: readonly string[], visibleNames: readonly string[]): string[] {
    const incoming = S.dedupe(visibleNames);
    const visible = new Set(incoming);
    const out: string[] = [];
    let i = 0;
    for (const name of base) {
        if (visible.has(name)) {
            if (i < incoming.length) out.push(incoming[i++] as string);
        } else {
            out.push(name);
        }
    }
    while (i < incoming.length) out.push(incoming[i++] as string);
    return S.dedupe(out).slice(0, S.MAX_REMEMBERED);
}

export function mergeOrder(visibleNames: readonly string[]): string[] {
    return mergeInto(S.current().order, visibleNames);
}

export function sameOrder(a: readonly string[], b: readonly string[]): boolean {
    return a.length === b.length && a.every((n, i) => n === b[i]);
}

export function togglePin(name: string, visibleNames: readonly string[]): boolean {
    const next = !S.isPinned(name);
    const pinned = next ? S.current().pinned.concat([name]) : S.current().pinned.filter((n) => n !== name);
    S.save(pinned, mergeOrder(visibleNames));
    return next;
}

export function pinSession(name: string): void {
    if (S.isPinned(name)) return;
    S.save(S.current().pinned.concat([name]), S.current().order);
}

export function move(name: string, delta: number, visibleNames: readonly string[]): MoveResult | null {
    const names = S.dedupe(visibleNames);
    const idx = names.indexOf(name);
    if (idx === -1) return null;
    const target = idx + (delta < 0 ? -1 : 1);
    if (target < 0 || target >= names.length) return null;
    const band = S.isPinned(name);
    const neighbourBand = S.isPinned(names[target] as string);
    const next = names.slice();
    next[idx] = names[target] as string;
    next[target] = name;
    const crossed = neighbourBand !== band;
    const nowPinned = crossed ? neighbourBand : band;
    const pinnedSet = crossed
        ? (nowPinned ? S.current().pinned.concat([name]) : S.current().pinned.filter((n) => n !== name))
        : S.current().pinned;
    S.save(pinnedSet, mergeOrder(next));
    return { order: next, crossed, pinned: nowPinned };
}

export function placeAt(
    name: string, targetPinned: boolean, beforeName: string | null | undefined, visibleNames: readonly string[],
): MoveResult | null {
    const names = S.dedupe(visibleNames);
    if (names.indexOf(name) === -1) return null;
    if (beforeName === name) return null;
    if (beforeName !== null && beforeName !== undefined && names.indexOf(beforeName) === -1) return null;
    const want = !!targetPinned;
    const rest = names.filter((n) => n !== name);
    let at = (beforeName === null || beforeName === undefined) ? rest.length : rest.indexOf(beforeName);
    if (at === -1) at = rest.length;
    const next = rest.slice(0, at).concat([name], rest.slice(at));
    const crossed = S.isPinned(name) !== want;
    if (!crossed && sameOrder(next, names)) return null;
    const pinnedSet = want ? S.current().pinned.concat([name]) : S.current().pinned.filter((n) => n !== name);
    S.save(pinnedSet, mergeOrder(next));
    return { order: next, crossed, pinned: want };
}

export function orderBand<T extends { name: string }>(key: string, rows: readonly T[]): T[] {
    const list = Array.isArray(rows) ? rows.slice() : [];
    if (!isBandOrderKey(key)) return list;
    const saved = S.bandOrder(key);
    if (!saved.length) return list;
    const rank = new Map(saved.map((n, i) => [n, i]));
    const known = list.filter((r) => rank.has(r.name))
        .sort((a, b) => (rank.get(a.name) as number) - (rank.get(b.name) as number));
    return known.concat(list.filter((r) => !rank.has(r.name)));
}

export function placeInBand(
    key: string, name: string, beforeName: string | null | undefined, bandNames: readonly string[],
): string[] | null {
    const names = S.dedupe(bandNames);
    if (names.indexOf(name) === -1 || beforeName === name) return null;
    const rest = names.filter((n) => n !== name);
    const at = (beforeName === null || beforeName === undefined) ? rest.length : rest.indexOf(beforeName);
    if (at === -1) return null;
    const next = rest.slice(0, at).concat([name], rest.slice(at));
    if (sameOrder(next, names)) return null;
    S.saveBandOrder(key, mergeInto(S.bandOrder(key), next).slice(0, S.MAX_REMEMBERED));
    return next;
}

export function moveInBand(key: string, name: string, delta: number, bandNames: readonly string[]): string[] | null {
    const names = S.dedupe(bandNames);
    const idx = names.indexOf(name);
    const target = idx + (delta < 0 ? -1 : 1);
    if (idx === -1 || target < 0 || target >= names.length) return null;
    const before = delta < 0 ? names[target] as string : (names[target + 1] || null);
    return placeInBand(key, name, before, names);
}
