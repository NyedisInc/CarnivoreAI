import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { REFRESH_THROTTLE_MS, TerminalListeners } from './terminal-listeners';
import type { DisposableLike, TermLike } from './types';

function fakeTerm(): { term: TermLike; fireWrite: () => void; fireScroll: () => void; writeSubs: number; scrollSubs: number } {
    let writeCb: (() => void) | null = null;
    let scrollCb: (() => void) | null = null;
    const state = { writeSubs: 0, scrollSubs: 0 };
    const term: TermLike = {
        onWriteParsed: (cb: () => void): DisposableLike => {
            writeCb = cb;
            state.writeSubs += 1;
            return { dispose: () => { state.writeSubs -= 1; if (writeCb === cb) writeCb = null; } };
        },
        onScroll: (cb: () => void): DisposableLike => {
            scrollCb = cb;
            state.scrollSubs += 1;
            return { dispose: () => { state.scrollSubs -= 1; if (scrollCb === cb) scrollCb = null; } };
        },
    };
    return {
        term,
        fireWrite: () => writeCb?.(),
        fireScroll: () => scrollCb?.(),
        get writeSubs() { return state.writeSubs; },
        get scrollSubs() { return state.scrollSubs; },
    };
}

let fake: ReturnType<typeof fakeTerm>;
let rescan: ReturnType<typeof vi.fn<() => void>>;
let viewportMoved: ReturnType<typeof vi.fn<() => void>>;
let listeners: TerminalListeners;

beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.useFakeTimers();
    fake = fakeTerm();
    rescan = vi.fn<() => void>();
    viewportMoved = vi.fn<() => void>();
    listeners = new TerminalListeners(
        { term: () => fake.term },
        { rescan, viewportMoved, held: () => true },
    );
});

afterEach(() => {
    listeners.detach();
    vi.useRealTimers();
    vi.restoreAllMocks();
});

describe('a write is reflected on a timer, not on the spot', () => {
    test('a single write does not rescan synchronously', () => {
        listeners.attach();
        fake.fireWrite();
        expect(rescan).not.toHaveBeenCalled();
    });

    test('it rescans once REFRESH_THROTTLE_MS has passed', () => {
        listeners.attach();
        fake.fireWrite();
        vi.advanceTimersByTime(REFRESH_THROTTLE_MS - 1);
        expect(rescan).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(rescan).toHaveBeenCalledTimes(1);
    });

    test('a burst of writes inside the window pays for ONE rescan, not one per write', () => {
        listeners.attach();
        fake.fireWrite();
        vi.advanceTimersByTime(REFRESH_THROTTLE_MS / 2);
        fake.fireWrite();
        fake.fireWrite();
        vi.advanceTimersByTime(REFRESH_THROTTLE_MS);
        expect(rescan).toHaveBeenCalledTimes(1);
    });

    test('the throttle re-arms for the NEXT burst once it has paid for this one', () => {
        listeners.attach();
        fake.fireWrite();
        vi.advanceTimersByTime(REFRESH_THROTTLE_MS);
        expect(rescan).toHaveBeenCalledTimes(1);
        fake.fireWrite();
        vi.advanceTimersByTime(REFRESH_THROTTLE_MS);
        expect(rescan).toHaveBeenCalledTimes(2);
    });

    test('detaching before the timer fires cancels the pending rescan', () => {
        listeners.attach();
        fake.fireWrite();
        listeners.detach();
        vi.advanceTimersByTime(REFRESH_THROTTLE_MS * 4);
        expect(rescan).not.toHaveBeenCalled();
    });
});

describe('a scroll only re-reads the viewport, on its own short timer', () => {
    test('a scroll does not rescan the buffer', () => {
        listeners.attach();
        fake.fireScroll();
        vi.advanceTimersByTime(REFRESH_THROTTLE_MS);
        expect(rescan).not.toHaveBeenCalled();
    });

    test('it reads the viewport well inside the write throttle window', () => {
        listeners.attach();
        fake.fireScroll();
        expect(viewportMoved).not.toHaveBeenCalled();
        vi.advanceTimersByTime(16);
        expect(viewportMoved).toHaveBeenCalledTimes(1);
    });

    test('a burst of scrolls before the frame pays for ONE read', () => {
        listeners.attach();
        fake.fireScroll();
        fake.fireScroll();
        fake.fireScroll();
        vi.advanceTimersByTime(16);
        expect(viewportMoved).toHaveBeenCalledTimes(1);
    });
});
