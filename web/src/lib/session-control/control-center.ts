import { authFetch, ApiError } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import type { BackgroundProcess, SessionBackgroundWork } from '../background-work/background-work';
import type { SubagentRow } from '../subagents/subagents';

export type ControlSection = 'timers' | 'agents' | 'processes';
export const CONTROL_SECTIONS: readonly ControlSection[] = ['timers', 'agents', 'processes'];

export const SESSION_CONTROL_OPTIONS = ['a', 'b', 'c'] as const;
export type SessionControlOption = (typeof SESSION_CONTROL_OPTIONS)[number];
export const DEFAULT_SESSION_CONTROL_OPTION: SessionControlOption = 'a';

export function resolveSessionControlOption(value: unknown): SessionControlOption {
  return (SESSION_CONTROL_OPTIONS as readonly unknown[]).includes(value)
    ? (value as SessionControlOption)
    : DEFAULT_SESSION_CONTROL_OPTION;
}

export interface TargetResult {
    pid: number;
    outcome: 'terminated' | 'killed' | 'still_running' | 'already_gone' | 'refused';
    code: string | null;
    detail: string;
}

export interface TerminateAllResponse {
    results: TargetResult[];
    term: number[];
    kill: number[];
    survivors: number[];
}

export interface InterruptResponse {
    sent: boolean;
    key: 'escape';
    agent_pid: number;
    activity_status: string | null;
    detail: string;
}

export function refreshKey(row: Record<string, unknown> | null | undefined): string {
    return JSON.stringify([
        row?.subagents_running ?? null, row?.subagents_total ?? null, row?.background_open ?? null,
        row?.timers_live ?? null, row?.timers_next_fire_at ?? null,
    ]);
}

export function processesOf(work: SessionBackgroundWork | null, agentId: string): BackgroundProcess[] {
    if (!work || work.state !== 'ok' || work.owners !== 'ok') return [];
    return work.processes.filter((p) => p.agent_id === agentId);
}

export function listedAgents(agents: readonly SubagentRow[], work: SessionBackgroundWork | null): SubagentRow[] {
    const owning = new Set((work?.processes ?? []).map((p) => p.agent_id).filter(Boolean));
    return agents
        .filter((a) => a.status === 'running' || owning.has(a.id))
        .sort((a, b) => {
            const ra = a.status === 'running' ? 0 : 1;
            const rb = b.status === 'running' ? 0 : 1;
            if (ra !== rb) return ra - rb;
            return (Date.parse(b.started_at ?? '') || 0) - (Date.parse(a.started_at ?? '') || 0);
        });
}

export interface WorkCounts {
    agents: number | null;
    shells: number | null;
}

export function workCounts(agentRows: readonly SubagentRow[] | null, work: SessionBackgroundWork | null): WorkCounts {
    return {
        agents: agentRows ? listedAgents(agentRows, work).filter((a) => a.status === 'running').length : null,
        shells: work?.state === 'ok' ? work.processes.length : null,
    };
}

export function terminateAll(sessionId: string, processes: readonly BackgroundProcess[]): Promise<TerminateAllResponse> {
    return authFetch<TerminateAllResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/background-work/terminate-all`,
        { method: 'POST', body: JSON.stringify({ targets: processes.map((p) => ({ pid: p.pid, start: p.start })) }) },
    );
}

export function interruptSession(sessionId: string): Promise<InterruptResponse> {
    return authFetch<InterruptResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/interrupt`,
        { method: 'POST', body: JSON.stringify({ confirm: true }) },
    );
}

function refusalCode(err: ApiError): string | null {
    const detail = (err.payload as { detail?: { code?: string } } | null)?.detail;
    return detail && typeof detail === 'object' && typeof detail.code === 'string' ? detail.code : null;
}

export function batchMessage(result: TerminateAllResponse | unknown): string {
    if (result && typeof result === 'object' && 'results' in result) {
        const rows = (result as TerminateAllResponse).results;
        const tally = (...outcomes: TargetResult['outcome'][]): number =>
            rows.filter((r) => outcomes.includes(r.outcome)).length;
        const parts: [string, number][] = [
            ['control_center.batch.stopped', tally('terminated', 'killed')],
            ['control_center.batch.gone', tally('already_gone')],
            ['control_center.batch.refused', tally('refused')],
            ['control_center.batch.running', tally('still_running')],
        ];
        const said = parts.filter(([, count]) => count > 0).map(([key, count]) => t(key, { count }));
        return said.length ? said.join(t('control_center.batch.join')) : t('control_center.batch.nothing');
    }
    const reason = result instanceof Error ? result.message : String(result);
    return t('control_center.batch.failed', { reason });
}

export function interruptMessage(result: InterruptResponse | unknown): string {
    if (result instanceof ApiError) {
        const code = refusalCode(result);
        return code ? t(`control_center.interrupt.refused.${code}`) : t('control_center.interrupt.failed', { reason: result.message });
    }
    if (result && typeof result === 'object' && 'sent' in result) return t('control_center.interrupt.sent');
    return t('control_center.interrupt.failed', { reason: String(result) });
}

function scrollBox(root: HTMLElement): HTMLElement | null {
    const candidates = [root, root.closest<HTMLElement>('[data-scroll-box]')];
    return candidates.find((box): box is HTMLElement => !!box && box.scrollHeight > box.clientHeight) ?? null;
}

export function revealInside(root: HTMLElement, el: HTMLElement): void {
    const box = scrollBox(root);
    if (!box) return;
    const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    const bottom = top + el.offsetHeight;
    if (top < box.scrollTop) box.scrollTop = top;
    else if (bottom > box.scrollTop + box.clientHeight) box.scrollTop = Math.max(0, Math.min(top, bottom - box.clientHeight));
}
