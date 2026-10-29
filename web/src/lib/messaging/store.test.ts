import { describe, expect, it } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { problemText, refusalReason } from './store.svelte';

const t = (key: string) => (key === 'messaging.ui.error.provider_unreachable' ? 'the provider did not answer.' : key);

function failure(detail: unknown): ApiError {
    return new ApiError('x', 502, null, { detail });
}

describe('problemText', () => {
    it('adds the providers own sentence after the catalog words', () => {
        const e = failure({ code: 'provider_unreachable', reason: 'The bridge is starting.' });
        expect(refusalReason(e)).toBe('The bridge is starting.');
        expect(problemText(e, t)).toBe('the provider did not answer. (The bridge is starting.)');
    });
    it('leaves the words alone when there is no reason', () => {
        expect(problemText(failure({ code: 'provider_unreachable' }), t)).toBe('the provider did not answer.');
    });
});
