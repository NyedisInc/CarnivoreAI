import { authFetch } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';

export type SubagentStatus = 'running' | 'done' | 'unknown';
export type SubagentsState = 'ok' | 'absent' | 'unchecked' | 'not_applicable';

export interface SubagentRow {
    id: string;
    agent_type: string | null;
    description: string | null;
    model: string | null;
    background: boolean | null;
    spawn_depth: number | null;
    started_at: string | null;
    last_activity_at: string | null;
    status: SubagentStatus;
    status_reason: string;
    end_status: string | null;
}

export interface SessionSubagents {
    state: SubagentsState;
    family: string | null;
    conversation_uuid: string | null;
    counts: {
        total: number;
        listed: number;
        running: number;
        done: number;
        unknown: number;
        shape_unrecognized: number;
        internal: number;
    } | null;
    subagents: SubagentRow[];
    detail: string;
    as_of: string | null;
}

export function fetchSubagents(sessionId: string): Promise<SessionSubagents> {
    return authFetch<SessionSubagents>(`/sessions/${encodeURIComponent(sessionId)}/subagents`);
}

export function runningCount(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : null;
}

export function runningTotal(rows: readonly { session?: { id?: string }; subagents_running?: number | null }[]): number {
    const seen = new Set<string>();
    let sum = 0;
    for (const row of rows) {
        const id = row.session?.id;
        const n = runningCount(row.subagents_running);
        if (n === null || (id !== undefined && seen.has(id))) continue;
        if (id !== undefined) seen.add(id);
        sum += n;
    }
    return sum;
}

export function measuredRunningTotal(
    rows: readonly { session?: { id?: string }; subagents_state?: string | null; subagents_running?: number | null }[],
): number | null {
    const seen = new Set<string>();
    let sum = 0;
    let measured = false;
    for (const row of rows) {
        if (row.subagents_state !== 'ok') continue;
        const id = row.session?.id;
        if (id !== undefined) {
            if (seen.has(id)) continue;
            seen.add(id);
        }
        measured = true;
        const raw = row.subagents_running;
        sum += typeof raw === 'number' && Number.isFinite(raw) ? Math.max(0, Math.floor(raw)) : 0;
    }
    return measured ? sum : null;
}

export function badgeText(running: number): string {
    return t('subagents.badge', { count: running });
}

export function badgeTitle(running: number, total: number | null | undefined): string {
    return t('subagents.badge.title', { count: running, total: total ?? running });
}

export function secondsSince(iso: string | null, nowMs: number): number | null {
    if (!iso) return null;
    const at = Date.parse(iso);
    if (!Number.isFinite(at)) return null;
    return Math.max(0, Math.floor((nowMs - at) / 1000));
}

export function emptyMessage(payload: SessionSubagents): string | null {
    if (payload.state === 'not_applicable') return t('subagents.list.not_applicable');
    if (payload.state === 'unchecked' || payload.counts === null) return t('subagents.list.unchecked');
    if (payload.subagents.length === 0) return t('subagents.list.empty');
    return null;
}

export function orderRows(rows: readonly SubagentRow[]): SubagentRow[] {
    const rank: Record<SubagentStatus, number> = { running: 0, unknown: 1, done: 2 };
    return [...rows].sort((a, b) => {
        const byStatus = rank[a.status] - rank[b.status];
        if (byStatus !== 0) return byStatus;
        return (Date.parse(b.last_activity_at ?? '') || 0) - (Date.parse(a.last_activity_at ?? '') || 0);
    });
}
