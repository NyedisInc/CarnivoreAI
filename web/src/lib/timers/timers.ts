import { authFetch } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';

export type TimerStatus =
    | 'live' | 'fired' | 'cancelled' | 'superseded' | 'expired'
    | 'lost' | 'refused' | 'unknown' | 'shape_unrecognized';
export type TimersState = 'ok' | 'absent' | 'unchecked' | 'not_applicable';

export interface TimerRow {
    id: string;
    kind: 'wakeup' | 'cron';
    status: TimerStatus;
    cron: string | null;
    human_schedule: string | null;
    delay_seconds: number | null;
    recurring: boolean | null;
    durable: boolean | null;
    created_at: string;
    fire_at: string | null;
    expires_at: string | null;
    prompt: string | null;
    reason: string | null;
}

export interface SessionTimers {
    state: TimersState;
    family: string | null;
    conversation_uuid: string | null;
    process: 'alive' | 'gone' | 'unknown';
    process_started_at: string | null;
    counts: {
        total: number;
        live: number;
        fired: number;
        cancelled: number;
        superseded: number;
        expired: number;
        lost: number;
        refused: number;
        unknown: number;
        shape_unrecognized: number;
    } | null;
    next_fire_at: string | null;
    timers: TimerRow[];
    background: BackgroundTasks | null;
    detail: string;
    as_of: string | null;
}

export interface ParkedEntry {
    task_id: string;
    kind: 'shell' | 'monitor';
    agent_id: string;
    live: boolean;
    started_at: string | null;
    summary: string;
}

export interface BackgroundTasks {
    open: number | null;
    detail: string;
    parked: ParkedEntry[];
}

export interface TimerFields {
    timers_live?: number | null;
    timers_next_fire_at?: string | null;
}

export function fetchTimers(sessionId: string): Promise<SessionTimers> {
    return authFetch<SessionTimers>(`/sessions/${encodeURIComponent(sessionId)}/timers`);
}

export function liveCount(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : null;
}

export function untilText(iso: string | null | undefined, nowMs: number): string | null {
    if (!iso) return null;
    const at = Date.parse(iso);
    if (!Number.isFinite(at)) return null;
    const seconds = (at - nowMs) / 1000;
    if (seconds <= 0) return t('timers.due');
    return durationText(seconds);
}

export function durationText(seconds: number): string {
    const minutes = Math.max(1, Math.ceil(seconds / 60));
    if (minutes < 60) return t('timers.in_minutes', { count: minutes });
    if (minutes < 60 * 24) return t('timers.in_hours', { count: Math.floor(minutes / 60) });
    return t('timers.in_days', { count: Math.floor(minutes / (60 * 24)) });
}

export function timerChip(row: TimerFields | null | undefined, nowMs: number): { text: string; title: string; live: number } | null {
    const live = liveCount(row?.timers_live);
    if (live === null) return null;
    const until = untilText(row?.timers_next_fire_at, nowMs);
    const text = until ?? t('timers.badge.count', { count: live });
    const title = until
        ? t('timers.badge.title', { count: live, time: until })
        : t('timers.badge.title_no_time', { count: live });
    return { text, title, live };
}

export function emptyMessage(payload: SessionTimers): string | null {
    if (payload.state === 'not_applicable') return t('timers.list.not_applicable');
    if (payload.state === 'unchecked') return t('timers.list.unchecked');
    if (payload.timers.length === 0) return t('timers.list.empty');
    return null;
}

export function orderRows(rows: readonly TimerRow[]): TimerRow[] {
    return [...rows].sort((a, b) => {
        const liveA = a.status === 'live' ? 0 : 1;
        const liveB = b.status === 'live' ? 0 : 1;
        if (liveA !== liveB) return liveA - liveB;
        if (liveA === 0) return (Date.parse(a.fire_at ?? '') || Infinity) - (Date.parse(b.fire_at ?? '') || Infinity);
        return (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0);
    });
}

export function scheduleText(row: TimerRow): string {
    if (row.kind === 'cron') return row.human_schedule ?? row.cron ?? t('timers.list.no_schedule');
    if (typeof row.delay_seconds === 'number' && row.delay_seconds > 0) {
        return t('timers.list.after_delay', { time: durationText(row.delay_seconds) });
    }
    return t('timers.list.no_schedule');
}
