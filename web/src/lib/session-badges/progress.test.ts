/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

vi.mock('../browser/select-push.svelte', () => ({ openPage: async () => ({}) }));

import { badgeSlotPlan } from './index';
import { applyBell, applyProgress, bellLit, BELL_LIGHT_MS } from './progress.svelte';

afterEach(() => { vi.useRealTimers(); });

describe('progress badge and bell light', () => {
    test('a frame draws the bar first, indeterminate is striped, a null state clears it, the bell lights then clears', async () => {
        const repaint = vi.fn();
        (globalThis as { SessionSidebar?: unknown }).SessionSidebar = { repaint };
        applyProgress({ session_id: 'ses_p1', state: 'normal', percent: 40 });
        const row = { session_id: 'ses_p1', ports: [{ port: 3000, address: '127.0.0.1' }] };
        const plan = badgeSlotPlan(row);
        expect(plan?.items[0]).toMatchObject({ kind: 'progress', text: '40%', pct: 40 });
        applyProgress({ session_id: 'ses_p1', state: 'indeterminate', percent: null });
        expect(badgeSlotPlan({ session: { id: 'ses_p1' } })?.items[0]).toMatchObject({ kind: 'progress', tone: 'stripe', pct: 100 });
        applyProgress({ session_id: 'ses_p1', state: null, percent: null });
        expect(badgeSlotPlan({ session_id: 'ses_p1' })).toBeNull();
        await Promise.resolve();
        expect(repaint).toHaveBeenCalled();

        vi.useFakeTimers();
        applyBell({ session_id: 'ses_p1' });
        expect(bellLit('ses_p1')).toBe(true);
        expect(bellLit('ses_other')).toBe(false);
        vi.advanceTimersByTime(BELL_LIGHT_MS + 1);
        expect(bellLit('ses_p1')).toBe(false);
    });
});
