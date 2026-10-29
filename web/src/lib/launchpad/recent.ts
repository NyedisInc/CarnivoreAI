import {
    RECENT_KEYS,
    recentCountLabel,
    recentCountUnavailableLabel,
    unavailableDetail,
} from '../../../../client/js/labels/recent-session.js';
import { closedWords } from './recent-closed';
import { visibleRecentRows, type LiveSession, type RecentRow } from './recent-visibility';

export type Translate = (key: string, params?: Record<string, unknown> | null) => string;

export interface RecentSessionRecord extends RecentRow {
    session_uuid?: string | null;
    lifecycle?: string | null;
    title?: string | null;
    working_dir?: string | null;
    agent_type?: string | null;
    closed_at?: string | null;
    closed_basis?: string | null;
}

export interface RecentSessionsPayload {
    state?: string | null;
    sessions?: RecentSessionRecord[] | null;
    notice?: string | null;
}

export interface RecentRowView {
    uuid: string;
    name: string;
    lifecycle: string;
    lifecycleLabel: string;
    lifecycleTitle: string;
    canRestart: boolean;
    archived: boolean;
    restart: RestartOptions | null;
}

export type RecentView =
    | { kind: 'hidden' }
    | { kind: 'unavailable'; state: string; title: string; detail: string; count: string }
    | { kind: 'empty'; count: string; message: string }
    | { kind: 'rows'; count: string; rows: RecentRowView[] };

export interface RestartOptions {
    sessionUuid: string;
    title: string;
    workingDir: string;
    agentType: string;
}

export interface RestartPlan {
    mode: 'restart' | 'create_unidentified';
    sessionUuid: string;
    payload: Record<string, string> | null;
    /* could not be determined */
    mustExplain: boolean;
}

const UNAVAILABLE_STATES = ['probe_unavailable', 'never_probed'];

export function stateOf(payload: RecentSessionsPayload | null | undefined): string {
    const raw = payload && typeof payload.state === 'string' ? payload.state.trim() : '';
    return raw || 'never_probed';
}

/* could not be determined */
export function restartPlan(opts: Partial<RestartOptions> | null | undefined): RestartPlan {
    const o = opts || {};
    const sessionUuid = (o.sessionUuid || '').trim();
    const title = (o.title || '').trim();
    const workingDir = (o.workingDir || '').trim();
    const agentType = (o.agentType || '').trim();
    if (sessionUuid) {
        return { mode: 'restart', sessionUuid, payload: null, mustExplain: false };
    }
    const payload: Record<string, string> = {};
    if (workingDir) payload.working_dir = workingDir;
    if (agentType) payload.agent_type = agentType;
    if (title) payload.project_name = title;
    return { mode: 'create_unidentified', sessionUuid: '', payload, mustExplain: true };
}

export function describeRow(
    row: RecentSessionRecord,
    deriveName: (tmuxName: string) => string | null,
    t: Translate,
    now: number = Date.now(),
): RecentRowView {
    const title = (row.title && String(row.title).trim()) || '';
    const name = title
        || (row.tmux_name ? deriveName(row.tmux_name) || '' : '')
        || row.working_dir
        || t(RECENT_KEYS.nameFallback);
    const lifecycle = (row.lifecycle && String(row.lifecycle)) || 'unknown';
    const canRestart = lifecycle === 'stopped';
    const closed = canRestart ? closedWords(row.closed_at, row.closed_basis, t, now) : null;
    return {
        uuid: (row.session_uuid && String(row.session_uuid)) || '',
        name,
        lifecycle,
        lifecycleLabel: closed ? closed.label : canRestart ? t(RECENT_KEYS.lifecycleEnded) : lifecycle,
        lifecycleTitle: closed ? closed.title : '',
        canRestart,
        archived: !!row.archived_at,
        restart: canRestart
            ? {
                sessionUuid: (row.session_uuid && String(row.session_uuid)) || '',
                title,
                workingDir: (row.working_dir && String(row.working_dir)) || '',
                agentType: (row.agent_type && String(row.agent_type)) || '',
            }
            : null,
    };
}

export function recentView(
    payload: RecentSessionsPayload | null | undefined,
    live: readonly LiveSession[] | null | undefined,
    showArchived: boolean,
    deriveName: (tmuxName: string) => string | null,
    t: Translate,
): RecentView {
    const state = stateOf(payload);
    if (state !== 'ok') {
        return {
            kind: 'unavailable',
            state,
            title: t(RECENT_KEYS.unavailableTitle),
            detail: unavailableDetail(payload ? payload.notice : null, t),
            count: recentCountUnavailableLabel(t),
        };
    }
    const all = (payload && payload.sessions) || [];
    const rows = visibleRecentRows(all, live);
    const count = recentCountLabel(rows.length, t);
    if (rows.length === 0) {
        if (showArchived) {
            return { kind: 'empty', count, message: t(RECENT_KEYS.emptyIncludingArchived) };
        }
        return { kind: 'hidden' };
    }
    return { kind: 'rows', count, rows: rows.map((r) => describeRow(r, deriveName, t)) };
}

export function isUnavailableState(state: string): boolean {
    return UNAVAILABLE_STATES.includes(state);
}
