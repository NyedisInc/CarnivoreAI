import { authFetch, ApiError } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';

export type BackgroundWorkState = 'ok' | 'absent' | 'unchecked' | 'not_applicable';

export interface BackgroundProcess {
    pid: number;
    start: string;
    task_id: string | null;
    started_at: string | null;
    children: number;
    summary: string | null;
    agent_id: string | null;
}

export interface SessionBackgroundWork {
    state: BackgroundWorkState;
    family: string | null;
    processes: BackgroundProcess[];
    owners: 'ok' | 'absent' | 'unchecked';
    detail: string;
    as_of: string | null;
}

export interface TerminateResponse {
    pid: number;
    outcome: 'terminated' | 'killed' | 'still_running' | 'already_gone';
    term: number[];
    kill: number[];
    survivors: number[];
    detail: string;
}

export function fetchBackgroundWork(sessionId: string): Promise<SessionBackgroundWork> {
    return authFetch<SessionBackgroundWork>(`/sessions/${encodeURIComponent(sessionId)}/background-work`);
}

export function terminateProcess(sessionId: string, process: BackgroundProcess): Promise<TerminateResponse> {
    return authFetch<TerminateResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/background-work/${process.pid}/terminate`,
        { method: 'POST', body: JSON.stringify({ start: process.start }) },
    );
}

export function stopMessage(result: TerminateResponse | unknown): string {
    if (result instanceof ApiError) {
        const detail = (result.payload as { detail?: { code?: string } } | null)?.detail;
        const code = detail && typeof detail === 'object' ? detail.code : null;
        return code
            ? t(`background_work.refused.${code}`)
            : t('background_work.stop.failed', { reason: result.message });
    }
    if (result && typeof result === 'object' && 'outcome' in result) {
        return t(`background_work.stop.${(result as TerminateResponse).outcome}`);
    }
    return t('background_work.stop.failed', { reason: String(result) });
}

export function processesEmpty(payload: SessionBackgroundWork): string | null {
    if (payload.state === 'not_applicable') return t('background_work.list.not_applicable');
    if (payload.state === 'unchecked') return t('background_work.list.unchecked');
    if (payload.state === 'absent') return t('background_work.list.absent');
    if (payload.processes.length === 0) return t('background_work.list.no_processes');
    return null;
}
