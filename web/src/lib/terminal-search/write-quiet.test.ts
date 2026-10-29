import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { QUIET_MAX_MS, QUIET_MS, whenWritesQuiet } from './write-quiet';

let listener: (() => void) | null = null;
const term = {
    onWriteParsed(cb: () => void) {
        listener = cb;
        return { dispose: () => { listener = null; } };
    },
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
    vi.useRealTimers();
    listener = null;
});

test('runs once the writes have been quiet long enough', () => {
    const work = vi.fn();
    whenWritesQuiet(term, work);
    vi.advanceTimersByTime(QUIET_MS - 50);
    listener?.();
    vi.advanceTimersByTime(QUIET_MS - 50);
    expect(work).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60);
    expect(work).toHaveBeenCalledTimes(1);
    expect(listener).toBeNull();
});

test('a pane that never goes quiet still runs at the cap, once', () => {
    const work = vi.fn();
    whenWritesQuiet(term, work);
    for (let t = 0; t < QUIET_MAX_MS + 1000; t += 100) {
        listener?.();
        vi.advanceTimersByTime(100);
    }
    expect(work).toHaveBeenCalledTimes(1);
});

test('cancel never runs the work and lets go of the listener', () => {
    const work = vi.fn();
    const cancel = whenWritesQuiet(term, work);
    cancel();
    vi.advanceTimersByTime(QUIET_MAX_MS * 2);
    expect(work).not.toHaveBeenCalled();
    expect(listener).toBeNull();
});

test('a terminal with no write event waits the quiet period and runs', () => {
    const work = vi.fn();
    whenWritesQuiet(null, work);
    vi.advanceTimersByTime(QUIET_MS + 1);
    expect(work).toHaveBeenCalledTimes(1);
});
