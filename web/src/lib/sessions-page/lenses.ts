import type { Translate } from '../sessions/types';
import type { PageRow, Signals } from './filters';

export const LENSES = [
    { key: 'project', icon: 'folder', glyph: true },
    { key: 'recent', icon: 'clock', glyph: true },
    { key: 'used', icon: 'chart', glyph: true },
    { key: 'dormant', icon: 'project-inactive', glyph: true },
    { key: 'pinned', icon: 'bar-pin', glyph: false },
    { key: 'provider', icon: 'bot', glyph: false },
    { key: 'computer', icon: 'computer', glyph: false },
    { key: 'needs', icon: 'bell', glyph: true },
    { key: 'convs', icon: 'chat', glyph: true },
] as const;
export type LensKey = (typeof LENSES)[number]['key'];

const NAMED: ReadonlySet<LensKey> = new Set<LensKey>(['project', 'provider', 'computer']);

export const DORMANT_DAYS = 14;
const HEAVY_S = 36_000;
const REGULAR_S = 7_200;
const DAY_MS = 86_400_000;

export const USED_TIERS: ReadonlyArray<readonly [string, (seconds: number) => boolean]> = [
    ['heavy', (s) => s >= HEAVY_S],
    ['regular', (s) => s >= REGULAR_S && s < HEAVY_S],
    ['light', (s) => s > 0 && s < REGULAR_S],
    ['none', (s) => s <= 0],
];

export const CONV_TIERS: ReadonlyArray<readonly [string, (n: number) => boolean]> = [
    ['6', (n) => n >= 6],
    ['3', (n) => n >= 3 && n < 6],
    ['2', (n) => n === 2],
    ['1', (n) => n <= 1],
];

export interface LensGroup {
    readonly key: string;
    readonly label: string;
    readonly bits: readonly string[];
    readonly measure: string;
    readonly rows: readonly PageRow[];
    readonly count: number;
    readonly live: number;
    readonly project: PageRow['projectRef'];
    readonly provider: string | null;
}

export interface LensContext {
    t: Translate;
    now: number;
    sig: Signals;
    isPinned(r: PageRow): boolean;
    /* could not be read */
    usage: Readonly<Record<string, number>> | null;
    conversations: Readonly<Record<string, number>>;
    age(iso: string | null): string;
    latest(r: PageRow): string;
    noCompany: string;
    thisComputer: string;
}

export const NEED_KINDS = ['question', 'startup', 'notice', 'finished_unread', 'asleep_unread'] as const;
export type NeedKind = (typeof NEED_KINDS)[number];

export function needKind(s: PageRow['s'], sig: Signals): NeedKind | null {
    const w = sig.live(s);
    if (w) {
        if (w.startup_gate === 'awaiting_startup_prompt') return 'startup';
        const a = w.activity_status;
        return a === 'question' || a === 'notice' || a === 'finished_unread' ? a : null;
    }
    return s.state === 'asleep' && sig.asleepUnread(s.session_uuid) ? 'asleep_unread' : null;
}

export function activityMs(r: PageRow): number {
    const at = Date.parse(r.s.last_activity_at ?? '');
    return Number.isFinite(at) ? at : 0;
}

export function byRecent(a: PageRow, b: PageRow): number {
    return activityMs(b) - activityMs(a);
}

function byLabel(a: { label: string }, b: { label: string }): number {
    return a.label.toLowerCase().localeCompare(b.label.toLowerCase());
}

function daysSince(ms: number, now: number): number {
    return ms > 0 ? Math.max(0, Math.floor((now - ms) / DAY_MS)) : 0;
}

function dayStart(ms: number): number {
    const d = new Date(ms);
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function recentBuckets(now: number): Array<[string, (ms: number) => boolean]> {
    const today = dayStart(now);
    return [
        ['today', (ms) => ms >= today],
        ['yesterday', (ms) => ms >= today - DAY_MS && ms < today],
        ['week', (ms) => ms >= now - 7 * DAY_MS && ms < today - DAY_MS],
        ['month', (ms) => ms >= now - 30 * DAY_MS && ms < now - 7 * DAY_MS],
        ['m60', (ms) => ms >= now - 60 * DAY_MS && ms < now - 30 * DAY_MS],
        ['old', (ms) => ms < now - 60 * DAY_MS],
    ];
}

function make(ctx: LensContext, key: string, label: string, bits: readonly string[], measure: string, rows: readonly PageRow[], extra: { project?: PageRow['projectRef']; provider?: string } = {}): LensGroup {
    const live = rows.filter((r) => r.s.state === 'running').length;
    const asleep = rows.length - live;
    const counts = [live ? ctx.t('sessions.page.group.running', { n: live }) : '', asleep ? ctx.t('sessions.page.group.asleep', { n: asleep }) : ''];
    return { key, label, bits: [...bits, ...counts].filter(Boolean), measure, rows, count: rows.length, live, project: extra.project ?? null, provider: extra.provider ?? null };
}

function bucket(rows: readonly PageRow[], key: (r: PageRow) => string): Map<string, PageRow[]> {
    const out = new Map<string, PageRow[]>();
    for (const r of rows) {
        const k = key(r);
        const list = out.get(k);
        if (list) list.push(r);
        else out.set(k, [r]);
    }
    return out;
}

function newest(rows: readonly PageRow[]): number {
    return rows.reduce((m, r) => Math.max(m, activityMs(r)), 0);
}

export function lensGroups(key: LensKey, rows: readonly PageRow[], ctx: LensContext): LensGroup[] {
    const { t } = ctx;
    let out: LensGroup[] = [];
    if (key === 'project' || key === 'dormant') {
        for (const [gk, list] of bucket(rows, (r) => r.groupKey)) {
            const first = list[0] as PageRow;
            const sorted = [...list].sort(byRecent);
            const days = daysSince(newest(list), ctx.now);
            const dormant = days >= DORMANT_DAYS;
            if (key === 'dormant' && !dormant) continue;
            const measure = dormant ? t('sessions.page.group.untouched', { days }) : t('sessions.page.group.touched', { age: newest(list) ? ctx.age(new Date(newest(list)).toISOString()) : '' });
            const company = first.company && first.company !== ctx.noCompany ? [first.company] : [];
            out.push(make(ctx, `${key}:${gk}`, first.project, company, measure, sorted, { project: first.projectRef }));
        }
        if (key === 'dormant') out.sort((a, b) => daysSince(newest(b.rows), ctx.now) - daysSince(newest(a.rows), ctx.now));
    } else if (key === 'recent') {
        const buckets = recentBuckets(ctx.now);
        for (const [bk, within] of buckets) {
            const list = rows.filter((r) => within(activityMs(r))).sort(byRecent);
            if (!list.length) continue;
            out.push(make(ctx, `recent:${bk}`, t(`sessions.page.lens.recent.${bk}`), [t('sessions.page.group.sessions', { n: list.length })], t('sessions.page.group.newest', { age: ctx.age(list[0]?.s.last_activity_at ?? null) }), list));
        }
    } else if (key === 'used') {
        const worked = (r: PageRow): number => ctx.usage?.[r.s.session_uuid] ?? 0;
        for (const [tk, within] of USED_TIERS) {
            const list = rows.filter((r) => within(worked(r))).sort((a, b) => worked(b) - worked(a) || byRecent(a, b));
            if (!list.length) continue;
            const total = list.reduce((n, r) => n + worked(r), 0);
            out.push(make(ctx, `used:${tk}`, t(`sessions.page.lens.used.${tk}`), [t(`sessions.page.lens.used.${tk}.sub`)], total ? t('sessions.page.group.worked', { h: Math.round(total / 3600) }) : '', list));
        }
    } else if (key === 'pinned') {
        const list = rows.filter((r) => ctx.isPinned(r)).sort(byRecent);
        if (list.length) out.push(make(ctx, 'pinned:all', t('sessions.page.lens.pinned'), [t('sessions.page.group.sessions', { n: list.length })], '', list));
    } else if (key === 'provider') {
        for (const [pk, list] of bucket(rows, (r) => r.provider)) out.push(make(ctx, `provider:${pk}`, pk, [t('sessions.page.group.sessions', { n: list.length })], '', [...list].sort(byRecent), { provider: pk }));
    } else if (key === 'computer') {
        for (const [ck, list] of bucket(rows, (r) => r.computer ?? ctx.thisComputer)) out.push(make(ctx, `computer:${ck}`, ck, [t('sessions.page.group.sessions', { n: list.length })], '', [...list].sort(byRecent)));
    } else if (key === 'needs') {
        const by = bucket(rows.filter((r) => needKind(r.s, ctx.sig)), (r) => needKind(r.s, ctx.sig) as string);
        for (const nk of NEED_KINDS) {
            const list = by.get(nk);
            if (!list) continue;
            const oldest = Math.min(...list.map((r) => activityMs(r) || ctx.now));
            out.push(make(ctx, `needs:${nk}`, t(`sessions.page.lens.needs.${nk}`), [], t('sessions.page.group.oldest', { age: ctx.age(new Date(oldest).toISOString()) }), [...list].sort(byRecent)));
        }
    } else {
        const convs = (r: PageRow): number => (ctx.conversations[r.s.session_uuid] ?? 0) + 1;
        for (const [ck, within] of CONV_TIERS) {
            if (ck === '1') continue;
            const list = rows.filter((r) => within(convs(r))).sort((a, b) => convs(b) - convs(a) || byRecent(a, b));
            if (list.length) out.push(make(ctx, `convs:${ck}`, t(`sessions.page.lens.convs.${ck}`), [t('sessions.page.group.sessions', { n: list.length })], '', list));
        }
    }
    if (NAMED.has(key)) out = out.sort(byLabel);
    return out;
}

export function lensMeasure(r: PageRow, key: LensKey, ctx: LensContext): string {
    if (key === 'used') {
        const s = ctx.usage?.[r.s.session_uuid];
        if (!s) return '';
        return s >= 3600 ? ctx.t('sessions.page.group.worked', { h: Math.round(s / 3600) }) : ctx.t('sessions.page.measure.worked_min', { m: Math.max(1, Math.round(s / 60)) });
    }
    if (key === 'dormant') return ctx.t('sessions.page.group.untouched', { days: daysSince(activityMs(r), ctx.now) });
    if (key === 'convs') return ctx.t('sessions.page.measure.convs', { n: (ctx.conversations[r.s.session_uuid] ?? 0) + 1 });
    return ctx.age(r.s.last_activity_at);
}

export function measureHeadingKey(key: LensKey): string {
    return key === 'used' ? 'sessions.page.col.measure.used' : key === 'dormant' ? 'sessions.page.col.measure.dormant' : 'sessions.page.col.measure';
}

const LENS_KEY = 'carnivore.sessions-page.lens';

export function readLens(): LensKey {
    try {
        const v = globalThis.localStorage?.getItem(LENS_KEY) ?? '';
        return LENSES.some((l) => l.key === v) ? (v as LensKey) : 'project';
    } catch {
        return 'project';
    }
}

export function writeLens(key: LensKey): void {
    try {
        globalThis.localStorage?.setItem(LENS_KEY, key);
    } catch {
    }
}
