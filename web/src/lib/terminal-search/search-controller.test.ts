import { beforeEach, afterEach, describe, expect, test, vi } from 'vitest';

import { SearchController, SESSION_WATCH_MS, TYPE_DEBOUNCE_MS } from './search-controller.svelte';
import { harness, settle } from './search-controller-harness';

let open: SearchController | null = null;

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    open?.close();
    open = null;
    vi.useRealTimers();
});

describe('opening', () => {
    test('the engine goes on the LIVE term and the rail is shown', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        expect(h.controller.isOpen()).toBe(true);
        expect(h.calls.attach).toHaveLength(1);
        expect(h.controller.rail.hidden).toBe(true);
        expect(h.calls.history).toEqual(['ses_a']);
    });

    test('the tmux history load is asked for, for THIS session', async () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        expect(h.controller.history).toBe('pending');
        await settle();
        expect(h.controller.history).toBe('painted');
    });

    test('a missing history module is `unavailable`, not `pending` forever', () => {
        const h = harness({ withHistory: false });
        open = h.controller;
        h.controller.open();
        expect(h.controller.history).toBe('unavailable');
        expect(h.controller.countText).toBe('searching recent output only');
    });

    test('a history load that threw degrades to `unavailable`', async () => {
        const h = harness({ historyResult: new Error('nope') });
        open = h.controller;
        vi.spyOn(console, 'warn').mockImplementation(() => {});
        h.controller.open();
        await settle();
        expect(h.controller.history).toBe('unavailable');
    });

    test('NEGATIVE: with no terminal attached, open does nothing at all', () => {
        const h = harness();
        (h.host as { term: () => null }).term = () => null;
        h.controller.open();
        expect(h.controller.isOpen()).toBe(false);
        expect(h.calls.attach).toEqual([]);
    });

    test('a second open refocuses and does not re-attach or re-fetch', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.open();
        expect(h.calls.attach).toHaveLength(1);
        expect(h.calls.history).toHaveLength(1);
    });
});

describe('typing', () => {
    test('nothing runs until the debounce elapses, then find and the rail filter do', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.onType();
        expect(h.calls.find).toEqual([]);
        vi.advanceTimersByTime(TYPE_DEBOUNCE_MS);
        expect(h.calls.find).toEqual([['hazard', 'prev']]);
        expect(h.calls.predicate).toEqual(['hazard']);
    });

    test('a burst of keystrokes pays for ONE search', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        for (const q of ['h', 'ha', 'haz']) {
            h.controller.query = q;
            h.controller.onType();
            vi.advanceTimersByTime(TYPE_DEBOUNCE_MS - 1);
        }
        vi.advanceTimersByTime(1);
        expect(h.calls.find).toEqual([['haz', 'prev']]);
    });

    test('a debounce that lands after a close runs nothing', () => {
        const h = harness();
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.onType();
        h.controller.close();
        vi.advanceTimersByTime(TYPE_DEBOUNCE_MS * 4);
        expect(h.calls.find).toEqual([]);
    });

    test('the counter reads the add-on report as it arrives', async () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        await settle();
        h.controller.query = 'hazard';
        h.world.onResults?.({ resultIndex: 1, resultCount: 4, limit: 1000 });
        expect(h.controller.countText).toBe('2 of 4');
    });
});

describe('walking matches', () => {
    test('step reaches both of the add-on\'s directions', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.step('next');
        h.controller.step('prev');
        expect(h.calls.next).toBe(1);
        expect(h.calls.prev).toBe(1);
    });

    test('NEGATIVE: with an empty query a step does nothing', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.step('next');
        expect(h.calls.next).toBe(0);
    });
});

describe('closing', () => {
    test('close drops every highlight, hides the rail and refocuses the pane', () => {
        const h = harness();
        h.controller.open();
        h.controller.close();
        expect(h.controller.isOpen()).toBe(false);
        expect(h.calls.clear).toBe(1);
        expect(h.controller.rail.hidden).toBe(true);
        expect(h.calls.focusTerm).toBe(1);
    });

    test('close unsubscribes from the add-on rather than leaking a listener', () => {
        const h = harness();
        h.controller.open();
        expect(h.world.onResults).not.toBeNull();
        h.controller.close();
        expect(h.world.onResults).toBeNull();
    });

    test('toggle opens then closes', () => {
        const h = harness();
        open = h.controller;
        h.controller.toggle();
        expect(h.controller.isOpen()).toBe(true);
        h.controller.toggle();
        expect(h.controller.isOpen()).toBe(false);
    });
});

describe('the session underneath', () => {
    test('a session switch closes the panel', () => {
        const h = harness();
        h.controller.open();
        h.world.sessionId = 'ses_b';
        vi.advanceTimersByTime(SESSION_WATCH_MS);
        expect(h.controller.isOpen()).toBe(false);
    });

    test('NEGATIVE: a null session id is not a mismatch and must not close it', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.world.sessionId = null;
        vi.advanceTimersByTime(SESSION_WATCH_MS * 3);
        expect(h.controller.isOpen()).toBe(true);
    });

    test('a history answer for a session we have left is discarded', async () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.world.sessionId = 'ses_b';
        vi.advanceTimersByTime(SESSION_WATCH_MS);
        await settle();
        expect(h.controller.isOpen()).toBe(false);
        expect(h.controller.history).toBeNull();
    });
});
