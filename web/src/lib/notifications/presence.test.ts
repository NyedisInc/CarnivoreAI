/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { BEAT_MS, IDLE_MS, startPresenceBeacon } from './presence';

let visibility: 'visible' | 'hidden' = 'visible';
let stop: (() => void) | null = null;
const posts: Array<[string, boolean]> = [];

function start(clientId: () => string | null = () => 'tab-12345678') {
    stop = startPresenceBeacon({ clientId, post: (id, active) => posts.push([id, active]), now: () => Date.now() });
}
const input = () => document.dispatchEvent(new Event('keydown'));
const setVisibility = (v: 'visible' | 'hidden') => { visibility = v; document.dispatchEvent(new Event('visibilitychange')); };

beforeEach(() => {
    vi.useFakeTimers();
    visibility = 'visible';
    posts.length = 0;
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
});
afterEach(() => { stop?.(); stop = null; vi.useRealTimers(); });

describe('presence beacon', () => {
    test('page load alone is not presence: no beat without input', () => {
        start();
        vi.advanceTimersByTime(BEAT_MS * 3);
        expect(posts).toEqual([]);
    });

    test('input while visible beats at once, then every 30 s', () => {
        start();
        input();
        expect(posts).toEqual([['tab-12345678', true]]);
        vi.advanceTimersByTime(BEAT_MS);
        vi.advanceTimersByTime(BEAT_MS);
        expect(posts.filter(([, a]) => a).length).toBe(3);
    });

    test('hiding the page sends active false once and stops the beats', () => {
        start();
        input();
        setVisibility('hidden');
        expect(posts.at(-1)).toEqual(['tab-12345678', false]);
        const count = posts.length;
        vi.advanceTimersByTime(BEAT_MS * 4);
        expect(posts.length).toBe(count);
        setVisibility('visible');
        expect(posts.at(-1)).toEqual(['tab-12345678', true]);
    });

    test('five minutes without input sends active false once and the beats stop', () => {
        start();
        input();
        vi.advanceTimersByTime(IDLE_MS + BEAT_MS);
        expect(posts.at(-1)).toEqual(['tab-12345678', false]);
        const count = posts.length;
        vi.advanceTimersByTime(BEAT_MS * 5);
        expect(posts.length).toBe(count);
        input();
        expect(posts.at(-1)).toEqual(['tab-12345678', true]);
    });

    test('input while hidden never beats; pagehide sends active false', () => {
        start();
        visibility = 'hidden';
        input();
        vi.advanceTimersByTime(BEAT_MS * 2);
        expect(posts).toEqual([]);
        setVisibility('visible');
        expect(posts.at(-1)).toEqual(['tab-12345678', true]);
        window.dispatchEvent(new Event('pagehide'));
        expect(posts.at(-1)).toEqual(['tab-12345678', false]);
    });

    test('no client id means no beat; stop removes the listeners and the timer', () => {
        start(() => null);
        input();
        vi.advanceTimersByTime(BEAT_MS);
        expect(posts).toEqual([]);
        stop?.();
        start();
        (stop as (() => void) | null)?.();
        stop = null;
        input();
        vi.advanceTimersByTime(BEAT_MS * 2);
        expect(posts).toEqual([]);
    });
});
