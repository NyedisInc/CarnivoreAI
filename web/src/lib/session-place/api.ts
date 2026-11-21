import { authFetch } from '../../opscenter/api/auth.svelte';
import type { Translate } from '../sessions/types';

export interface PlacementQuestion {
    working_dir: string;
    agent_type?: string;
}

export interface PlacementBlock {
    decision: 'here' | 'remote' | 'refused';
    computer: string | null;
    label: string | null;
    reason: string;
    code: string | null;
    left_behind?: number | null;
}

export interface PlacedAnswer {
    session: Record<string, unknown>;
    placement: PlacementBlock;
}

export interface SessionPlaceApi {
    explain(question: PlacementQuestion): Promise<PlacementBlock>;
    start(body: Record<string, unknown>): Promise<PlacedAnswer>;
}

const SHOWN_LIMIT = 160;

export function clean(text: unknown): string {
    // eslint-disable-next-line no-control-regex -- stripping control bytes is the point
    return typeof text === 'string' ? text.replace(/[\u0000-\u001f\u007f-\u009f]/g, '').slice(0, SHOWN_LIMIT) : '';
}

export function readPlacement(raw: unknown): PlacementBlock {
    const p = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
    const decision = p['decision'] === 'here' || p['decision'] === 'remote' ? p['decision'] : 'refused';
    const left = typeof p['left_behind'] === 'number' ? p['left_behind'] : null;
    return {
        decision,
        computer: typeof p['computer'] === 'string' ? clean(p['computer']) : null,
        label: typeof p['label'] === 'string' ? clean(p['label']) : null,
        reason: clean(p['reason']),
        code: typeof p['code'] === 'string' ? clean(p['code']) : null,
        left_behind: left,
    };
}

export const sessionPlaceApi: SessionPlaceApi = {
    explain: async (question) => {
        const answer = await authFetch<{ placement?: unknown }>('/pack/session-placement/explain', { method: 'POST', body: JSON.stringify(question) });
        return readPlacement(answer?.placement);
    },
    start: async (body) => {
        const answer = await authFetch<{ session: Record<string, unknown>; placement?: unknown }>('/sessions/auto', { method: 'POST', body: JSON.stringify(body) });
        return { session: answer.session, placement: readPlacement(answer.placement) };
    },
};

export function newRequestId(): string {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function refusalReason(error: unknown): string {
    const payload = (error as { payload?: unknown } | null)?.payload as { detail?: { placement?: { reason?: unknown } } } | null | undefined;
    return clean(payload?.detail?.placement?.reason);
}

export function startedLine(placement: PlacementBlock, t: Translate): string {
    const here = t('launch_picker.computer.here');
    const where = placement.decision === 'remote' ? (placement.label || placement.computer || '') : here;
    const parts = [t('launchpad.status.started_on', { computer: where, reason: placement.reason })];
    if (placement.decision === 'remote') {
        if (placement.left_behind) parts.push(t('launchpad.status.left_behind', { count: placement.left_behind, computer: here }));
        parts.push(t('launchpad.status.work_stays', { computer: where }));
    }
    return parts.join('; ');
}
