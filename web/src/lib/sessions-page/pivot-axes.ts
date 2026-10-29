import type { Translate } from '../sessions/types';
import { activityMs, CONV_TIERS, needKind, recentBuckets, USED_TIERS } from './lenses';
import { writeChoice } from './stored-choice';
import { matchesFind, type PageRow, type Signals } from './filters';

export const AXIS_ORDER = ['project', 'company', 'provider', 'computer', 'state', 'recency', 'used', 'hour', 'weekday', 'convs'] as const;
export type AxisKey = (typeof AXIS_ORDER)[number];

const NEEDS_HISTORY: ReadonlySet<AxisKey> = new Set<AxisKey>(['recency', 'used', 'hour', 'weekday', 'convs']);

export const NO_DATA = '_none';

export interface PivotContext {
    t: Translate;
    now: number;
    sig: Signals;
    usage: Readonly<Record<string, number>> | null;
    conversations: Readonly<Record<string, number>>;
    noCompany: string;
    thisComputer: string;
    find?: string;
}

export interface Bucket {
    readonly id: string;
    readonly label: string;
    readonly sub: string;
    readonly short: string;
    readonly wide?: boolean;
    readonly letter?: string;
    readonly projectId?: number | null;
    readonly companyName?: string;
    readonly provider?: string;
}

export interface Tally {
    n: number;
    live: number;
    newest: number;
}

export interface PivotModel {
    readonly rows: readonly Bucket[];
    readonly cols: readonly Bucket[];
    readonly cells: ReadonlyMap<string, readonly PageRow[]>;
    readonly rowTally: ReadonlyMap<string, Tally>;
    readonly colTally: ReadonlyMap<string, Tally>;
    readonly misses: ReadonlySet<string>;
}

export function unavailable(key: AxisKey, flags: { historyFailed: boolean; listingDown: boolean }): 'history' | 'live' | null {
    if (NEEDS_HISTORY.has(key) && flags.historyFailed) return 'history';
    if (key === 'state' && flags.listingDown) return 'live';
    return null;
}

function bucketPart(s: string): string {
    return encodeURIComponent(s);
}

export function workedAtMs(r: PageRow): number {
    const work = Date.parse(r.s.last_work_at ?? '');
    return Number.isFinite(work) ? work : activityMs(r);
}

export function weekdayIndex(ms: number): number {
    return (new Date(ms).getDay() + 6) % 7;
}

function dayPart(ms: number): number {
    return Math.floor(new Date(ms).getHours() / 6);
}

const DAY_PARTS = ['night', 'morning', 'afternoon', 'evening'] as const;
const STATES = ['needs', 'working', 'idle', 'unk', 'asleep'] as const;

function stateOf(r: PageRow, sig: Signals): (typeof STATES)[number] {
    if (needKind(r.s, sig)) return 'needs';
    if (r.s.state === 'asleep') return 'asleep';
    const status = sig.live(r.s)?.activity_status;
    if (status === 'working' || status === 'working_subagent') return 'working';
    return status === 'idle' ? 'idle' : 'unk';
}

function dayWord(ms: number): string {
    return new Date(ms).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase();
}

export function axisOf(key: AxisKey, r: PageRow, ctx: PivotContext): string {
    switch (key) {
        case 'project':
            return `p${r.groupKey}`;
        case 'company':
            return `co-${bucketPart(r.company ?? ctx.noCompany)}`;
        case 'provider':
            return `ag-${r.provider}`;
        case 'computer':
            return `pc-${bucketPart(r.computer ?? ctx.thisComputer)}`;
        case 'state':
            return `st-${stateOf(r, ctx.sig)}`;
        case 'recency': {
            const ms = activityMs(r);
            return ms ? (recentBuckets(ctx.now).find(([, within]) => within(ms))?.[0] ?? NO_DATA) : NO_DATA;
        }
        case 'used': {
            const worked = ctx.usage?.[r.s.session_uuid] ?? 0;
            return `u-${USED_TIERS.find(([, within]) => within(worked))?.[0] ?? 'none'}`;
        }
        case 'hour': {
            const ms = workedAtMs(r);
            return ms ? `h-${DAY_PARTS[dayPart(ms)]}` : NO_DATA;
        }
        case 'weekday': {
            const ms = workedAtMs(r);
            return ms ? `d${weekdayIndex(ms)}` : NO_DATA;
        }
        default: {
            const n = (ctx.conversations[r.s.session_uuid] ?? 0) + 1;
            return `c${CONV_TIERS.find(([, within]) => within(n))?.[0] ?? '1'}`;
        }
    }
}

function byNewest(a: { newest: number; label: string }, b: { newest: number; label: string }): number {
    return b.newest - a.newest || a.label.localeCompare(b.label);
}

function axisBuckets(key: AxisKey, rows: readonly PageRow[], ctx: PivotContext): Bucket[] {
    const { t } = ctx;
    const newestOf = (id: string, axis: AxisKey): number => rows.reduce((m, r) => (axisOf(axis, r, ctx) === id ? Math.max(m, activityMs(r)) : m), 0);
    if (key === 'project') {
        const seen = new Map<string, PageRow>();
        for (const r of rows) if (!seen.has(r.groupKey)) seen.set(r.groupKey, r);
        return [...seen.values()]
            .map((r) => ({ id: `p${r.groupKey}`, label: r.project, sub: r.company ?? ctx.noCompany, short: (r.project.charAt(0) || '?').toUpperCase(), letter: (r.project.charAt(0) || '?').toUpperCase(), projectId: r.projectRef?.id ?? null, newest: newestOf(`p${r.groupKey}`, 'project') }))
            .sort(byNewest);
    }
    if (key === 'company') {
        const names = [...new Set(rows.map((r) => r.company ?? ctx.noCompany))];
        return names
            .map((name) => ({ id: `co-${bucketPart(name)}`, label: name, sub: '', short: name === ctx.noCompany ? t('sessions.page.pivot.none_short') : name.slice(0, 5), ...(name === ctx.noCompany ? {} : { letter: name.replace(/[^A-Za-z0-9]/g, '').charAt(0).toUpperCase() || '?', companyName: name }), newest: newestOf(`co-${bucketPart(name)}`, 'company') }))
            .sort(byNewest);
    }
    if (key === 'provider') {
        return ['claude', 'codex'].filter((p) => rows.some((r) => r.provider === p)).map((p) => ({ id: `ag-${p}`, label: p, sub: '', short: p, provider: p }));
    }
    if (key === 'computer') {
        const names = [...new Set(rows.map((r) => r.computer ?? ctx.thisComputer))];
        return names
            .sort((a, b) => (a === ctx.thisComputer ? -1 : b === ctx.thisComputer ? 1 : a.localeCompare(b)))
            .map((name) => ({ id: `pc-${bucketPart(name)}`, label: name, sub: '', short: name === ctx.thisComputer ? t('sessions.page.pivot.here') : name }));
    }
    if (key === 'state') {
        return STATES.map((s) => ({ id: `st-${s}`, label: t(`sessions.page.pivot.state.${s}`), sub: s === 'needs' || s === 'unk' ? t(`sessions.page.pivot.state.${s}.sub`) : '', short: t(`sessions.page.pivot.state.${s}.short`) }));
    }
    if (key === 'recency') {
        const day = 86_400_000;
        const sub: Record<string, string> = {
            today: dayWord(ctx.now),
            yesterday: dayWord(ctx.now - day),
            week: `${dayWord(ctx.now - 7 * day)} ${t('sessions.page.pivot.to')} ${dayWord(ctx.now - 2 * day)}`,
            month: `${dayWord(ctx.now - 30 * day)} ${t('sessions.page.pivot.to')} ${dayWord(ctx.now - 8 * day)}`,
            m60: `${dayWord(ctx.now - 60 * day)} ${t('sessions.page.pivot.to')} ${dayWord(ctx.now - 31 * day)}`,
            old: `${t('sessions.page.pivot.before')} ${dayWord(ctx.now - 60 * day)}`,
        };
        return recentBuckets(ctx.now).map(([k]) => ({ id: k, label: t(`sessions.page.lens.recent.${k}`), sub: sub[k] ?? '', short: t(`sessions.page.pivot.recent.${k}.short`), wide: true }));
    }
    if (key === 'used') {
        return USED_TIERS.map(([k]) => ({ id: `u-${k}`, label: t(`sessions.page.lens.used.${k}`), sub: t(`sessions.page.lens.used.${k}.sub`), short: k === 'none' ? t('sessions.page.pivot.none_short') : t(`sessions.page.lens.used.${k}`) }));
    }
    if (key === 'hour') {
        return DAY_PARTS.map((p) => ({ id: `h-${p}`, label: t(`sessions.page.pivot.hour.${p}`), sub: t(`sessions.page.pivot.hour.${p}.sub`), short: t(`sessions.page.pivot.hour.${p}`) }));
    }
    if (key === 'weekday') {
        const today = weekdayIndex(ctx.now);
        return Array.from({ length: 7 }, (_, i) => ({ id: `d${i}`, label: t(`sessions.page.pivot.wd.${i}`), sub: i === today ? t('sessions.page.pivot.today') : '', short: t(`sessions.page.pivot.wd.${i}.short`) }));
    }
    return CONV_TIERS.map(([k]) => ({ id: `c${k}`, label: t(`sessions.page.pivot.convs.${k}`), sub: t('sessions.page.pivot.convs.sub'), short: t(`sessions.page.pivot.convs.${k}.short`) }));
}

export function buildPivot(rows: readonly PageRow[], rowKey: AxisKey, colKey: AxisKey, ctx: PivotContext): PivotModel {
    const rb = axisBuckets(rowKey, rows, ctx);
    const cb = axisBuckets(colKey, rows, ctx);
    const cells = new Map<string, PageRow[]>();
    const rowTally = new Map<string, Tally>();
    const colTally = new Map<string, Tally>();
    let needRow = false;
    let needCol = false;
    const bump = (m: Map<string, Tally>, id: string, r: PageRow): void => {
        const t = m.get(id) ?? { n: 0, live: 0, newest: 0 };
        t.n += 1;
        if (r.s.state === 'running') t.live += 1;
        t.newest = Math.max(t.newest, activityMs(r));
        m.set(id, t);
    };
    for (const r of rows) {
        const a = axisOf(rowKey, r, ctx);
        const c = axisOf(colKey, r, ctx);
        needRow ||= a === NO_DATA;
        needCol ||= c === NO_DATA;
        const k = `${a}|${c}`;
        const list = cells.get(k);
        if (list) list.push(r);
        else cells.set(k, [r]);
        bump(rowTally, a, r);
        bump(colTally, c, r);
    }
    for (const list of cells.values()) list.sort((x, y) => activityMs(y) - activityMs(x));
    const none: Bucket = { id: NO_DATA, label: ctx.t('sessions.page.pivot.no_data'), sub: ctx.t('sessions.page.pivot.no_data.sub'), short: ctx.t('sessions.page.pivot.none_short') };
    if (needRow) rb.push(none);
    if (needCol) cb.push(none);
    const misses = new Set<string>();
    if (ctx.find?.trim()) for (const r of rows) if (!matchesFind(r, ctx.find)) misses.add(r.s.session_uuid);
    return { rows: rb, cols: cb, cells, rowTally, colTally, misses };
}

const PREFS_KEY = 'carnivore.sessions-page.pivot';

export interface PivotPrefs {
    rows: AxisKey;
    cols: AxisKey;
    dens: 'detail' | 'compact';
}

export const DEFAULT_PREFS: Readonly<PivotPrefs> = { rows: 'project', cols: 'recency', dens: 'detail' };

export function readPrefs(): PivotPrefs {
    try {
        const raw = JSON.parse(globalThis.localStorage?.getItem(PREFS_KEY) ?? '{}') as Partial<PivotPrefs>;
        const ok = (k: unknown): k is AxisKey => (AXIS_ORDER as readonly unknown[]).includes(k);
        const rows = ok(raw.rows) ? raw.rows : DEFAULT_PREFS.rows;
        const cols = ok(raw.cols) && raw.cols !== rows ? raw.cols : rows === DEFAULT_PREFS.cols ? DEFAULT_PREFS.rows : DEFAULT_PREFS.cols;
        return { rows, cols, dens: raw.dens === 'compact' ? 'compact' : 'detail' };
    } catch {
        return { ...DEFAULT_PREFS };
    }
}

export function writePrefs(prefs: PivotPrefs): void {
    writeChoice(PREFS_KEY, JSON.stringify(prefs));
}
