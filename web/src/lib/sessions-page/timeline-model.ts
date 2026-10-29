import type { SessionTimeline } from '../../opscenter/cells/timeline/types';
import { projectColorVar } from '../project-colors/palette';
import { needsYou, type PageRow, type Signals } from './filters';

export const WINDOWS = [
    { key: '1h', min: 60 },
    { key: '6h', min: 360 },
    { key: '24h', min: 1440 },
    { key: '7d', min: 10080 },
] as const;
export type WindowKey = (typeof WINDOWS)[number]['key'];

export interface Span {
    readonly x0: number;
    readonly x1: number;
}

export interface BookmarkTick {
    readonly x: number;
    readonly bookmarkId: number;
    readonly label: string;
    readonly at: string;
}

export interface LaneDraw {
    readonly span: Span | null;
    readonly busy: readonly Span[];
    readonly waits: readonly (Span & { readonly kind: 'question' | 'notice' | 'done' })[];
    readonly sleeps: readonly Span[];
    readonly marks: readonly BookmarkTick[];
    readonly measured: boolean;
}

const MIN = 60000;

function ms(iso: string | null | undefined): number {
    return iso ? Date.parse(iso) : Number.NaN;
}

function pct(t: number, nowMs: number, windowMin: number): number {
    const before = (nowMs - t) / MIN;
    return Math.max(0, Math.min(100, ((windowMin - before) / windowMin) * 100));
}

function spanOf(a: number, b: number, nowMs: number, windowMin: number): Span | null {
    const end = Number.isNaN(b) ? nowMs : b;
    if (Number.isNaN(a) || end <= nowMs - windowMin * MIN || a >= nowMs) return null;
    const x0 = pct(a, nowMs, windowMin);
    const x1 = pct(end, nowMs, windowMin);
    return x1 > x0 ? { x0, x1 } : null;
}

export function layoutLane(tl: SessionTimeline | null, windowMin: number, nowMs: number): LaneDraw {
    if (!tl) return { span: null, busy: [], waits: [], sleeps: [], marks: [], measured: false };
    let from = Number.POSITIVE_INFINITY;
    let to = Number.NEGATIVE_INFINITY;
    const busy: Span[] = [];
    let measured = false;
    for (const bar of tl.bars) {
        const a = ms(bar.started_at);
        const sp = spanOf(a, ms(bar.ended_at), nowMs, windowMin);
        if (!sp) continue;
        from = Math.min(from, sp.x0);
        to = Math.max(to, sp.x1);
        if (bar.activity) measured = true;
        for (const run of bar.activity ?? []) {
            if (run.state !== 'busy') continue;
            const b = spanOf(ms(run.start), ms(run.end), nowMs, windowMin);
            if (b) busy.push(b);
        }
    }
    const waits = (tl.attention ?? []).flatMap((w) => {
        const sp = spanOf(ms(w.start), ms(w.end), nowMs, windowMin);
        return sp ? [{ ...sp, kind: (w.kind === 'done' ? 'done' : w.kind === 'notice' ? 'notice' : 'question') as 'question' | 'notice' | 'done' }] : [];
    });
    const sleeps = tl.gaps.flatMap((g) => {
        const sp = spanOf(ms(g.start), ms(g.end), nowMs, windowMin);
        return sp ? [sp] : [];
    });
    const marks = tl.marks.flatMap((m) => {
        const at = ms(m.at);
        if (m.kind !== 'bookmark' || m.bookmark_id === null || Number.isNaN(at) || at < nowMs - windowMin * MIN || at > nowMs) return [];
        return [{ x: pct(at, nowMs, windowMin), bookmarkId: m.bookmark_id, label: m.label, at: m.at as string }];
    });
    return { span: Number.isFinite(from) ? { x0: from, x1: to } : null, busy, waits, sleeps, marks, measured };
}

export interface Moment {
    readonly cat: 'working' | 'waiting' | 'quiet' | 'unknown' | 'asleep';
    readonly status: string;
    readonly unread: boolean;
}

function within(t: number, start: string, end: string | null): boolean {
    return t >= ms(start) && (end === null || t < ms(end));
}

export function momentOf(tl: SessionTimeline | null, minBefore: number, nowMs: number): Moment {
    const unknown: Moment = { cat: 'unknown', status: 'unknown', unread: false };
    if (!tl) return unknown;
    const t = nowMs - minBefore * MIN;
    if (tl.gaps.some((g) => within(t, g.start, g.end))) return { cat: 'asleep', status: 'asleep', unread: false };
    const wait = (tl.attention ?? []).find((w) => within(t, w.start, w.end));
    if (wait) {
        if (wait.kind === 'done') return { cat: 'waiting', status: 'finished_unread', unread: true };
        return { cat: 'waiting', status: wait.kind === 'notice' ? 'notice' : 'question', unread: false };
    }
    for (const bar of tl.bars) {
        if (!within(t, bar.started_at ?? '', bar.ended_at)) continue;
        const run = (bar.activity ?? []).find((r) => within(t, r.start, r.end));
        if (run) return run.state === 'busy' ? { cat: 'working', status: 'working', unread: false } : { cat: 'quiet', status: 'idle', unread: false };
        return bar.activity ? { cat: 'quiet', status: 'idle', unread: false } : unknown;
    }
    return unknown;
}

export interface Tick {
    readonly m: number;
    readonly major: boolean;
    readonly label: string;
}

const STEPS = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440];

function hhmm(a: number): string {
    const t = ((a % 1440) + 1440) % 1440;
    return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
}

export function rulerTicks(nowMs: number, windowMin: number, widthPx: number): Tick[] {
    const ppm = (widthPx || 800) / windowMin;
    const major = STEPS.find((s) => s * ppm >= 64) ?? 1440;
    const minor = STEPS.find((s) => s < major && major % s === 0 && s * ppm >= 14) ?? null;
    const offset = new Date(nowMs).getTimezoneOffset();
    const nowLocal = Math.floor(nowMs / MIN) - offset;
    const out: Tick[] = [];
    const walk = (step: number, isMajor: boolean): void => {
        for (let a = Math.ceil((nowLocal - windowMin) / step) * step; a <= nowLocal; a += step) {
            const m = nowLocal - a;
            if (m <= 0 || m >= windowMin - 0.5 || (!isMajor && a % major === 0)) continue;
            let label = '';
            if (isMajor && m * ppm > 40) {
                const midnight = a % 1440 === 0;
                const day = new Date((a + offset) * MIN).toLocaleDateString('en-US', { weekday: 'short' }).toLowerCase();
                label = midnight ? day + (major < 1440 ? ' 00:00' : '') : hhmm(a);
            }
            out.push({ m, major: isMajor, label });
        }
    };
    if (minor) walk(minor, false);
    walk(major, true);
    return out;
}

export interface LaneGroup {
    readonly key: string;
    readonly project: string;
    readonly projectRef: PageRow['projectRef'];
    readonly rows: readonly PageRow[];
}

export interface LanePlan {
    readonly needs: readonly LaneGroup[];
    readonly running: readonly LaneGroup[];
    readonly asleep: readonly LaneGroup[];
    readonly fold: readonly LaneGroup[];
}

export function lastActivityMs(r: PageRow): number {
    const times = [ms(r.s.last_activity_at), ms(r.s.last_work_at), ms(r.s.last_seen_running_at)].filter(Number.isFinite);
    return times.length ? Math.max(...times) : Number.NaN;
}

const laneName = (r: PageRow): string => r.s.label ?? r.s.title ?? '';

const alpha = (a: string, b: string): number => a.localeCompare(b, undefined, { sensitivity: 'base' });

export function byProject(rows: readonly PageRow[]): LaneGroup[] {
    const map = new Map<string, PageRow[]>();
    for (const r of rows) {
        const key = r.projectRef ? r.groupKey : NO_PROJECT_KEY;
        map.set(key, [...(map.get(key) ?? []), r]);
    }
    return [...map.entries()]
        .flatMap(([key, list]) => {
            const first = list[0];
            return first ? [{ key, project: first.project, projectRef: first.projectRef, rows: list.sort((a, b) => alpha(laneName(a), laneName(b))) }] : [];
        })
        .sort((a, b) => (a.projectRef === null ? 1 : 0) - (b.projectRef === null ? 1 : 0) || alpha(a.project, b.project));
}

const NO_PROJECT_KEY = '__no_project';

export function laneColor(ref: PageRow['projectRef'], colorOf: (id: number | null) => string | null): string | undefined {
    const stored = ref ? colorOf(ref.id ?? null) : null;
    return stored ? projectColorVar(stored) : undefined;
}

export function planLanes(rows: readonly PageRow[], sig: Signals, windowMin: number, nowMs: number): LanePlan {
    const needs: PageRow[] = [];
    const running: PageRow[] = [];
    const asleep: PageRow[] = [];
    const fold: PageRow[] = [];
    for (const r of rows) {
        if (needsYou(r.s, sig)) needs.push(r);
        else if (r.s.state === 'running') running.push(r);
        else if (lastActivityMs(r) >= nowMs - windowMin * MIN) asleep.push(r);
        else fold.push(r);
    }
    return { needs: byProject(needs), running: byProject(running), asleep: byProject(asleep), fold: byProject(fold) };
}

export function liveMoment(asleep: boolean, asleepUnread: boolean, live: { activity_status?: string | null; unread?: boolean | null; startup_gate?: string | null } | undefined): Moment | (Omit<Moment, 'cat'> & { cat: 'dead' }) {
    if (asleep) return { cat: 'asleep', status: 'asleep', unread: asleepUnread };
    if (!live) return { cat: 'unknown', status: 'unknown', unread: false };
    const status = live.activity_status ?? 'unknown';
    const unread = live.unread === true;
    if (live.startup_gate === 'awaiting_startup_prompt') return { cat: 'waiting', status: 'question', unread };
    if (status === 'working' || status === 'working_subagent') return { cat: 'working', status, unread };
    if (status === 'question' || status === 'notice' || status === 'finished_unread') return { cat: 'waiting', status, unread };
    if (status === 'idle') return { cat: 'quiet', status, unread };
    if (status === 'dead') return { cat: 'dead', status, unread };
    return { cat: 'unknown', status: 'unknown', unread };
}
