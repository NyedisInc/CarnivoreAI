/* and the real */
import type { Translate } from '../sessions/types';
import { canWithdraw, isOpen, stageKey, stageOf, type FolderPhase } from './stages';
import type { SubRow } from './types';

export type WaitState = 'submitted' | 'running' | 'in_review' | 'approved' | 'stuck' | 'publishing';

export type CheckWhy = 'new' | 'again' | 'withdrawn' | 'revoked' | 'no_appeal';

export type Step =
    | { kind: 'wait'; sub: SubRow; state: WaitState; withdraw: boolean }
    | { kind: 'fix'; local: boolean; sub: SubRow | null }
    | { kind: 'appeal'; sub: SubRow; left: number }
    | { kind: 'check'; why: CheckWhy; sub: SubRow | null }
    | { kind: 'send' }
    | { kind: 'live'; sub: SubRow };

export interface StepInput {
    latest: SubRow | null;
    withdrawn: SubRow | null;
    phase: FolderPhase;
    force: boolean;
}

export function waitState(sub: Pick<SubRow, 'status' | 'gate_state'>): WaitState {
    if (sub.status === 'publishing') return 'publishing';
    if (sub.status === 'approved') return 'approved';
    switch (sub.gate_state) {
        case 'received': return 'submitted';
        case 'gating': return 'running';
        case 'stuck': return 'stuck';
        default: return 'in_review';
    }
}

export function stepOf(input: StepInput): Step {
    const { latest, withdrawn, phase, force } = input;
    const open = latest !== null && isOpen(latest);
    if (latest && open && phase !== 'checked') return { kind: 'wait', sub: latest, state: waitState(latest), withdraw: canWithdraw(latest) };
    if (phase === 'checked') return { kind: 'send' };
    if (force && !open) return { kind: 'check', why: 'again', sub: latest };
    if (phase === 'refused') return { kind: 'fix', local: true, sub: latest };
    if (withdrawn) return { kind: 'check', why: 'withdrawn', sub: withdrawn };
    if (latest) {
        if (latest.status === 'gate_failed') return { kind: 'fix', local: false, sub: latest };
        if (latest.status === 'rejected') {
            const left = latest.appeals_left ?? 0;
            return left > 0 ? { kind: 'appeal', sub: latest, left } : { kind: 'check', why: 'no_appeal', sub: latest };
        }
        if (latest.status === 'revoked') return { kind: 'check', why: 'revoked', sub: latest };
        if (latest.status === 'published') return { kind: 'live', sub: latest };
    }
    return { kind: 'check', why: latest ? 'again' : 'new', sub: latest };
}

export function isWizard(step: Step): boolean {
    return step.kind === 'send' || step.kind === 'check';
}

export function stepperIndex(step: Step): number | null {
    return step.kind === 'wait' ? 3 : null;
}

export function waitLeadKey(state: WaitState): string {
    return `publish.page.next.${state}.lead`;
}

export function leadText(step: Step, checkedVersion: string, t: Translate): string {
    if (step.kind === 'send') return t('publish.page.next.checked.lead', { version: checkedVersion });
    if (step.kind !== 'check') return '';
    const sub = step.sub;
    switch (step.why) {
        case 'again': return t('publish.page.next.again.lead');
        case 'withdrawn': return t('publish.page.next.withdrawn.lead', { version: sub?.version ?? '' });
        case 'revoked': return t('publish.page.next.revoked.lead', { reason: sub?.revocation_reason || sub?.reason || t('publish.page.timeline.revoked.default_reason') });
        case 'no_appeal': return t('publish.page.next.no_appeal.lead', { reason: sub?.reason ?? '' });
        default: return '';
    }
}

export function stageWordOf(sub: SubRow, t: Translate): string {
    const stage = stageOf(sub);
    return stage ? t(stageKey(stage)) : '';
}
