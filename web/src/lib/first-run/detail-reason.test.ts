import { describe, expect, it } from 'vitest';
import { detailReasonOf } from './detail-reason';

describe('detailReasonOf', () => {
    it('reads detail.reason and answers empty for anything else', () => {
        expect(detailReasonOf({ detail: { reason: 'bad_link' } })).toBe('bad_link');
        expect(detailReasonOf({ detail: { reason: 3 } })).toBe('');
        expect(detailReasonOf({ detail: 'x' })).toBe('');
        expect(detailReasonOf(null)).toBe('');
    });
});
