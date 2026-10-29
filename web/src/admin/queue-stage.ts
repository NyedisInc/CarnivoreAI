import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';
import { stageOf } from '../lib/publish-page/stages';

export type QueueStage = 'submitted' | 'in_review' | 'approved' | 'rejected';

export const QUEUE_STAGES: ReadonlyArray<{ id: QueueStage; key: string }> = [
    { id: 'submitted', key: ADMIN_KEYS.queueStageSubmitted },
    { id: 'in_review', key: ADMIN_KEYS.queueStageInReview },
    { id: 'approved', key: ADMIN_KEYS.queueStageApproved },
    { id: 'rejected', key: ADMIN_KEYS.queueStageRejected },
];

export const DEFAULT_QUEUE_STAGE: QueueStage = 'in_review';

export const QUEUE_STATUSES: readonly string[] = [
    'pending', 'publishing', 'approved', 'published', 'superseded', 'gate_failed', 'rejected', 'revoked', 'withdrawn',
];

export interface StageRow {
    status?: string;
    gate_state?: string;
}

const ADMIN_EXTRAS: Record<string, QueueStage> = { superseded: 'approved', withdrawn: 'rejected' };

export function queueStageOf(row: StageRow): QueueStage {
    const status = row.status || '';
    return ADMIN_EXTRAS[status] ?? stageOf({ status, gate_state: row.gate_state }) ?? 'in_review';
}

export type WordTone = 'good' | 'bad' | 'quiet';

export function statusWord(row: StageRow): { key: string; tone: WordTone } {
    const status = row.status || '';
    if (status === 'pending') {
        if (row.gate_state === 'received') return { key: ADMIN_KEYS.queueWordReceived, tone: 'quiet' };
        if (row.gate_state === 'gating') return { key: ADMIN_KEYS.queueWordGating, tone: 'quiet' };
        if (row.gate_state === 'stuck') return { key: ADMIN_KEYS.queueWordStuck, tone: 'bad' };
        return { key: ADMIN_KEYS.queueWordAwaiting, tone: 'quiet' };
    }
    const words: Record<string, { key: string; tone: WordTone }> = {
        publishing: { key: ADMIN_KEYS.queueWordPublishing, tone: 'quiet' },
        approved: { key: ADMIN_KEYS.queueWordApproved, tone: 'good' },
        published: { key: ADMIN_KEYS.queueWordPublished, tone: 'good' },
        superseded: { key: ADMIN_KEYS.queueWordSuperseded, tone: 'quiet' },
        gate_failed: { key: ADMIN_KEYS.queueWordGateFailed, tone: 'bad' },
        rejected: { key: ADMIN_KEYS.queueWordRejected, tone: 'bad' },
        revoked: { key: ADMIN_KEYS.queueWordRevoked, tone: 'bad' },
        withdrawn: { key: ADMIN_KEYS.queueWordWithdrawn, tone: 'quiet' },
    };
    return words[status] ?? { key: ADMIN_KEYS.queueWordAwaiting, tone: 'quiet' };
}

export function mergeNewestFirst<T extends { submission_id: string; created_at?: string }>(lists: T[][]): T[] {
    const seen = new Set<string>();
    const out: T[] = [];
    for (const row of lists.flat()) {
        if (seen.has(row.submission_id)) continue;
        seen.add(row.submission_id);
        out.push(row);
    }
    return out.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
}
