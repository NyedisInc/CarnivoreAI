import type { RunningSessionRow } from '../sessions/types';

export interface OneShotTarget {
    sessionId: string;
    label: string;
    tmuxName: string | null;
    agent: string | null;
}

function text(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
}

export function oneShotTargets(
    rows: readonly RunningSessionRow[] | null | undefined,
): OneShotTarget[] {
    const targets: OneShotTarget[] = [];
    for (const row of rows || []) {
        if (!row) continue;
        const sessionId = text(row.session_id);
        if (!sessionId) continue;
        const agent =
            text(row.agent_wrapper_label) || text(row.agent_type) || text(row.agent_family);
        if (!agent) continue;
        const tmuxName = text(row.name);
        targets.push({
            sessionId,
            label: text(row.label) || tmuxName || sessionId,
            tmuxName,
            agent,
        });
    }
    return targets;
}

export interface OneShotReport {
    pastedBytes: number | null;
    strippedCount: number | null;
    submitted: boolean | null;
}

export function oneShotReport(result: unknown): OneShotReport {
    const body = (result && typeof result === 'object' ? result : {}) as Record<string, unknown>;
    const count = (value: unknown): number | null =>
        typeof value === 'number' && Number.isFinite(value) ? value : null;
    const submitted = body.submitted;
    return {
        pastedBytes: count(body.pasted_bytes),
        strippedCount: count(body.stripped_count),
        submitted: typeof submitted === 'boolean' ? submitted : null,
    };
}
