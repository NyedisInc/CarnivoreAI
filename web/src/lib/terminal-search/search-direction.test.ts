import { beforeEach, afterEach, describe, expect, test, vi } from 'vitest';

import { SearchController } from './search-controller.svelte';
import { SEARCH_DIRECTION_KEY, uiPrefs } from '../ui/prefs.svelte';
import { harness } from './search-controller-harness';

let open: SearchController | null = null;

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    open?.close();
    open = null;
    vi.useRealTimers();
});

function fakeStorage(): { getItem: (k: string) => string | null; setItem: (k: string, v: string) => void; seen: Map<string, string> } {
    const seen = new Map<string, string>();
    return {
        seen,
        getItem: (k) => (seen.has(k) ? (seen.get(k) as string) : null),
        setItem: (k, v) => {
            seen.set(k, v);
        },
    };
}

describe('which end of the scrollback a search starts from', () => {
    beforeEach(() => {
        Object.defineProperty(globalThis, 'localStorage', {
            value: fakeStorage(),
            configurable: true,
            writable: true,
        });
        uiPrefs.resetForTests();
    });

    afterEach(() => {
        uiPrefs.resetForTests();
    });

    test('nothing stored means BOTTOM UP, and absent is never top down', () => {
        const h = harness();
        expect(h.controller.direction).toBe('bottom_up');
    });

    test('NEGATIVE: a value no version of this ever wrote reads as bottom up', () => {
        localStorage.setItem(SEARCH_DIRECTION_KEY, 'sideways');
        uiPrefs.resetForTests();
        const h = harness();
        expect(h.controller.direction).toBe('bottom_up');
    });

    test('a stored top down is honoured', () => {
        localStorage.setItem(SEARCH_DIRECTION_KEY, 'top_down');
        uiPrefs.resetForTests();
        const h = harness();
        expect(h.controller.direction).toBe('top_down');
    });

    test('BOTTOM UP runs the query as findPrevious, so the first hit is the newest', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.runQuery();
        expect(h.calls.find).toEqual([['hazard', 'prev']]);
    });

    test('BOTTOM UP clears the selection first, or the add-on restarts from it', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.runQuery();
        expect(h.calls.clearSelection).toBe(1);
    });

    test('NEGATIVE: TOP DOWN runs findNext and clears no selection', () => {
        localStorage.setItem(SEARCH_DIRECTION_KEY, 'top_down');
        uiPrefs.resetForTests();
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.runQuery();
        expect(h.calls.find).toEqual([['hazard', 'next']]);
        expect(h.calls.clearSelection).toBe(0);
    });

    test('BOTTOM UP: enter walks UP to older matches, shift+enter walks down', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.step('next');
        expect(h.calls.prev).toBe(1);
        expect(h.calls.next).toBe(0);
        h.controller.step('prev');
        expect(h.calls.next).toBe(1);
    });

    test('TOP DOWN: enter walks down, shift+enter walks up', () => {
        localStorage.setItem(SEARCH_DIRECTION_KEY, 'top_down');
        uiPrefs.resetForTests();
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.step('next');
        expect(h.calls.next).toBe(1);
        expect(h.calls.prev).toBe(0);
        h.controller.step('prev');
        expect(h.calls.prev).toBe(1);
    });

    test('the toggle flips the direction and writes it down', () => {
        const h = harness();
        open = h.controller;
        h.controller.toggleDirection();
        expect(h.controller.direction).toBe('top_down');
        expect(localStorage.getItem(SEARCH_DIRECTION_KEY)).toBe('top_down');
        h.controller.toggleDirection();
        expect(h.controller.direction).toBe('bottom_up');
        expect(localStorage.getItem(SEARCH_DIRECTION_KEY)).toBe('bottom_up');
    });

    test('a flipped direction is what the NEXT query is run with', () => {
        const h = harness();
        open = h.controller;
        h.controller.open();
        h.controller.query = 'hazard';
        h.controller.toggleDirection();
        h.controller.runQuery();
        expect(h.calls.find).toEqual([['hazard', 'next']]);
    });
});

