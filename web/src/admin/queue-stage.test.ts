import { describe, expect, it } from 'vitest';
import { queueStageOf, type QueueStage } from './queue-stage';

const TABLE: Array<[string, string | undefined, QueueStage]> = [
    ['pending', 'received', 'submitted'],
    ['pending', 'gating', 'in_review'],
    ['pending', 'stuck', 'in_review'],
    ['pending', 'unknown_state', 'in_review'],
    ['pending', undefined, 'in_review'],
    ['publishing', undefined, 'in_review'],
    ['publishing', 'received', 'in_review'],
    ['approved', undefined, 'approved'],
    ['published', undefined, 'approved'],
    ['superseded', undefined, 'approved'],
    ['gate_failed', undefined, 'rejected'],
    ['rejected', undefined, 'rejected'],
    ['revoked', undefined, 'rejected'],
    ['withdrawn', undefined, 'rejected'],
    ['', undefined, 'in_review'],
    ['some_future_status', undefined, 'in_review'],
];

describe('queueStageOf', () => {
    it.each(TABLE)('%s / %s is %s', (status, gate_state, stage) => {
        expect(queueStageOf({ status, gate_state })).toBe(stage);
    });
    it('a row with no status is in review', () => {
        expect(queueStageOf({})).toBe('in_review');
    });
    it('a media-only row is not dropped from the queue', () => {
        expect(queueStageOf({ status: 'approved', media_only: true } as never)).toBe('approved');
    });
});
