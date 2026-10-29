/* the newest match */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { harness, settle as settleMicro } from './search-controller-harness';
import { QUIET_MS } from './write-quiet';

beforeEach(() => {
    vi.useFakeTimers();
});
afterEach(() => {
    vi.useRealTimers();
});

async function settle(): Promise<void> {
    await settleMicro();
    await vi.advanceTimersByTimeAsync(QUIET_MS + 1);
}

describe('openAt lands on the named match, counted from the bottom', () => {
    test('waits for history, then finds from the bottom and steps up', async () => {
        const h = harness();
        h.controller.openAt('hazard', 2);
        expect(h.controller.opened).toBe(true);
        expect(h.controller.query).toBe('hazard');
        expect(h.calls.find).toEqual([]);
        await settle();
        expect(h.calls.find).toEqual([['hazard', 'prev']]);
        expect(h.calls.prev).toBe(2);
        expect(h.calls.clearSelection).toBe(1);
    });

    test('the newest match is zero steps', async () => {
        const h = harness();
        h.controller.openAt('hazard', 0);
        await settle();
        expect(h.calls.find).toEqual([['hazard', 'prev']]);
        expect(h.calls.prev).toBe(0);
    });

    test('with no history module it lands on what the buffer holds', async () => {
        const h = harness({ withHistory: false });
        h.controller.openAt('hazard', 1);
        await settle();
        expect(h.calls.find).toEqual([['hazard', 'prev']]);
        expect(h.calls.prev).toBe(1);
    });

    test('a failed history pull still lands', async () => {
        const h = harness({ historyResult: new Error('boom') });
        h.controller.openAt('hazard', 1);
        await settle();
        expect(h.calls.find).toEqual([['hazard', 'prev']]);
        expect(h.calls.prev).toBe(1);
    });

    test('already open on this session: replaces the query and lands', async () => {
        const h = harness();
        h.controller.open();
        await settle();
        h.controller.openAt('second', 3);
        await settle();
        expect(h.calls.find).toEqual([['second', 'prev']]);
        expect(h.calls.prev).toBe(3);
    });

    test('open on another session: reopens on this one', async () => {
        const h = harness();
        h.controller.open();
        await settle();
        h.world.sessionId = 'ses_b';
        h.controller.openAt('hazard', 0);
        expect(h.calls.history).toEqual(['ses_a', 'ses_b']);
        await settle();
        expect(h.calls.find).toEqual([['hazard', 'prev']]);
    });

    test('a close while waiting for the paint to settle cancels the jump', async () => {
        const h = harness();
        h.controller.openAt('hazard', 2);
        await settleMicro();
        h.controller.close();
        await vi.advanceTimersByTimeAsync(QUIET_MS * 10);
        expect(h.calls.find).toEqual([]);
    });

    test('a close before the history lands cancels the jump', async () => {
        const h = harness();
        h.controller.openAt('hazard', 2);
        h.controller.close();
        await settle();
        expect(h.calls.find).toEqual([]);
        expect(h.calls.prev).toBe(0);
    });
});
