import { describe, expect, it } from 'vitest';
import { canRetry, planLogRow } from './log-row';

const t = (key: string): string => key;
const MAY = 'may have been sent; do not resend: Restarted mid-send.';

describe('planLogRow', () => {
    it('shows unconfirmed as its own state with the reason and a hint, and never offers a resend', () => {
        const plan = planLogRow(t, { status: 'unconfirmed', direction: 'out', reason: MAY });
        expect(plan.statusText).toBe(`messaging.ui.status.unconfirmed (${MAY})`);
        expect(plan.hint).toBe('messaging.ui.log.unconfirmed_hint');
        expect(plan.retry).toBe(false);
    });

    it('keeps failed as failed, with a retry only for an inbound row', () => {
        expect(planLogRow(t, { status: 'failed', direction: 'in', reason: 'delivery_uncertain' })).toMatchObject({ retry: true, hint: null });
        expect(planLogRow(t, { status: 'failed', direction: 'out', reason: 'provider_refused' })).toMatchObject({ retry: false, hint: null });
        expect(planLogRow(t, { status: 'failed', direction: 'out', reason: null }).statusText).toBe('messaging.ui.status.failed');
    });

    it('never retries an unconfirmed row whatever its direction', () => {
        expect(canRetry({ status: 'unconfirmed', direction: 'in' })).toBe(false);
        expect(canRetry({ status: 'unconfirmed', direction: 'out' })).toBe(false);
    });
});
