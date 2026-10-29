import { LEGACY_TMUX_SESSION_PREFIXES, TMUX_SESSION_PREFIX } from '../product-identity';
import * as S from './store';

export const CURRENT_PREFIX = TMUX_SESSION_PREFIX;

export const LEGACY_PREFIXES: readonly string[] = LEGACY_TMUX_SESSION_PREFIXES;

export interface RebindRow {
    name?: string;
    session_uuid?: string | null;
}

export interface RebindInput {
    pinned?: string[];
    order?: string[];
    ids?: Record<string, string>;
    bands?: Record<string, string[]>;
}

export interface RebindOutput {
    pinned: string[];
    order: string[];
    bands: Record<string, string[]>;
    ids: Record<string, string>;
    moved: Array<[string, string]>;
}

export function rebind(stored: RebindInput, rows: readonly RebindRow[]): RebindOutput {
    const live = new Map<string, RebindRow>();
    const byUuid = new Map<string, string>();
    for (const r of rows || []) {
        if (!r || !r.name) continue;
        live.set(r.name, r);
        if (r.session_uuid) byUuid.set(r.session_uuid, r.name);
    }
    const ids: Record<string, string> = { ...(stored.ids || {}) };
    const bands = (stored.bands && typeof stored.bands === 'object') ? stored.bands : {};
    const bandLists = Object.keys(bands).map((k) => (Array.isArray(bands[k]) ? bands[k] as string[] : []));
    const remembered = new Set<string>(([] as string[]).concat(stored.pinned || [], stored.order || [], ...bandLists));

    const target = (name: string): string | null => {
        if (live.has(name)) return null;
        const uuid = ids[name];
        if (uuid && byUuid.has(uuid)) return byUuid.get(uuid) as string;
        for (const p of LEGACY_PREFIXES) {
            if (name.indexOf(p) !== 0) continue;
            const cand = CURRENT_PREFIX + name.slice(p.length);
            const row = live.get(cand);
            if (!row) return null;
            if (uuid && row.session_uuid && row.session_uuid !== uuid) return null;
            return cand;
        }
        return null;
    };

    const plan = new Map<string, string>();
    const claims = new Map<string, number>();
    remembered.forEach((name) => {
        const to = target(name);
        if (!to) return;
        plan.set(name, to);
        claims.set(to, (claims.get(to) || 0) + 1);
    });
    const moved: Array<[string, string]> = [];
    plan.forEach((to, from) => {
        if ((claims.get(to) || 0) > 1) plan.delete(from);
        else moved.push([from, to]);
    });

    const map = (list: readonly string[] | undefined): string[] => {
        const seen = new Set<string>();
        return (list || []).map((n) => plan.get(n) || n)
            .filter((n) => {
                if (seen.has(n)) return false;
                seen.add(n);
                return true;
            });
    };
    plan.forEach((to, from) => {
        if (ids[from] && !ids[to]) ids[to] = ids[from] as string;
        delete ids[from];
    });
    live.forEach((row, name) => {
        if (row.session_uuid) ids[name] = row.session_uuid;
    });
    const nextBands: Record<string, string[]> = {};
    for (const k of Object.keys(bands)) nextBands[k] = map(bands[k]);
    return { pinned: map(stored.pinned), order: map(stored.order), bands: nextBands, ids, moved };
}

export function reconcile(rows: readonly RebindRow[]): Array<[string, string]> {
    const st = S.current();
    if (!st || st.status !== 'ok') return [];
    const out = rebind(st, rows);
    const same = (a: readonly string[], b: readonly string[]): boolean =>
        a.length === b.length && a.every((x, i) => x === b[i]);
    const canon = (o: Record<string, string>): string =>
        JSON.stringify(Object.keys(o).sort().map((k) => [k, o[k]]));
    const bandNames = Object.keys(out.bands).reduce<string[]>((acc, k) => acc.concat(out.bands[k] || []), []);
    const names = new Set(out.pinned.concat(out.order, bandNames));
    const kept: Record<string, string> = {};
    for (const n of Object.keys(out.ids)) if (names.has(n)) kept[n] = out.ids[n] as string;
    const bandsSame = JSON.stringify(out.bands) === JSON.stringify(st.bands || {});
    if (same(out.pinned, st.pinned) && same(out.order, st.order) && bandsSame
        && canon(kept) === canon(S.readIds(st.ids))) {
        return [];
    }
    S.save(out.pinned, out.order, undefined, out.ids, out.bands);
    if (out.moved.length) {
        console.log(`SessionSidebarStoreRebind: carried ${out.moved.length} remembered session(s) to their new names`);
    }
    return out.moved;
}
