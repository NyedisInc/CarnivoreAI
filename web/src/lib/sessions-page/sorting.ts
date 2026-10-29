import { activityMs, byRecent, needKind, lensMeasure, type LensContext, type LensGroup, type LensKey } from './lenses';
import type { PageRow } from './filters';

export const COLUMNS = ['name', 'state', 'proj', 'prov', 'latest', 'measure', 'comp', 'start'] as const;
export type ColumnKey = (typeof COLUMNS)[number];

export interface SortState {
    readonly k: ColumnKey;
    readonly dir: 1 | -1;
}

const FIRST_IS_ASCENDING: Readonly<Record<ColumnKey, boolean>> = { name: true, state: true, proj: true, prov: true, latest: true, measure: false, comp: true, start: false };

const lc = (v: string | null | undefined): string => (v ?? '').toLowerCase();

const byText = (f: (r: PageRow) => string) => (a: PageRow, b: PageRow): number => lc(f(a)).localeCompare(lc(f(b)));

function stateRank(r: PageRow, ctx: LensContext): number {
    if (needKind(r.s, ctx.sig)) return 0;
    const status = ctx.sig.live(r.s)?.activity_status ?? '';
    if (status === 'working' || status === 'working_subagent') return 1;
    return r.s.state === 'running' ? 2 : 3;
}

function comparator(k: ColumnKey, lens: LensKey, ctx: LensContext): (a: PageRow, b: PageRow) => number {
    switch (k) {
        case 'name':
            return byText((r) => r.s.label ?? r.s.title);
        case 'state':
            return (a, b) => stateRank(a, ctx) - stateRank(b, ctx);
        case 'proj':
            return byText((r) => r.project);
        case 'prov':
            return byText((r) => r.provider);
        case 'latest':
            return byText((r) => ctx.latest(r));
        case 'comp':
            return byText((r) => r.computer ?? ctx.thisComputer);
        case 'start':
            return (a, b) => (Date.parse(b.s.created_at ?? '') || 0) - (Date.parse(a.s.created_at ?? '') || 0);
        default:
            return lens === 'used'
                ? (a, b) => (ctx.usage?.[b.s.session_uuid] ?? 0) - (ctx.usage?.[a.s.session_uuid] ?? 0)
                : lens === 'convs'
                  ? (a, b) => (ctx.conversations[b.s.session_uuid] ?? 0) - (ctx.conversations[a.s.session_uuid] ?? 0)
                  : byRecent;
    }
}

export function sortGroups(groups: readonly LensGroup[], sort: SortState | null, lens: LensKey, ctx: LensContext): LensGroup[] {
    if (!sort) return [...groups];
    const cmp = comparator(sort.k, lens, ctx);
    return groups.map((g) => ({ ...g, rows: [...g.rows].sort((a, b) => sort.dir * (cmp(a, b) || activityMs(b) - activityMs(a))) }));
}

export function nextSort(current: SortState | null, k: ColumnKey): SortState {
    return current?.k === k ? { k, dir: current.dir === 1 ? -1 : 1 } : { k, dir: 1 };
}

export function ariaSort(sort: SortState | null, k: ColumnKey): 'ascending' | 'descending' | null {
    if (sort?.k !== k) return null;
    return (sort.dir === 1) === FIRST_IS_ASCENDING[k] ? 'ascending' : 'descending';
}

export const measureText = lensMeasure;
