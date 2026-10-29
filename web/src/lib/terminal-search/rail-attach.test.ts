import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { RailModel } from './rail-model.svelte';
import type { DisposableLike, MarkerLike, PromptScanApi, ScannedPrompt } from './types';

/** One scanned prompt, as the scanner reports it. */
function prompt(ordinal: number, line: number, text: string): ScannedPrompt {
    return { ordinal, line, text, full: text, preview: text.slice(0, 80) };
}

let live: RailModel | null = null;

beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.useFakeTimers();
});

afterEach(() => {
    live?.dispose();
    live = null;
    vi.useRealTimers();
    vi.restoreAllMocks();
});

function countingTerm(viewportY = 0): {
    term: Record<string, unknown>;
    live: () => number;
    setViewport: (y: number) => void;
} {
    const buffer: Record<string, unknown> = {
        type: 'normal',
        baseY: 0,
        cursorY: 0,
        viewportY,
        length: 1000,
    };
    let attached = 0;
    const subscribe = (): DisposableLike => {
        attached += 1;
        let gone = false;
        return {
            dispose: () => {
                if (gone) return;
                gone = true;
                attached -= 1;
            },
        };
    };
    return {
        term: {
            cols: 80,
            rows: 24,
            get buffer() {
                return { active: buffer };
            },
            registerMarker: (offset: number) => ({
                line: offset,
                isDisposed: false,
                dispose(this: MarkerLike) {
                    this.isDisposed = true;
                },
            }),
            scrollToLine: () => {},
            onWriteParsed: () => subscribe(),
            onScroll: () => subscribe(),
        },
        live: () => attached,
        setViewport: (y) => {
            buffer.viewportY = y;
        },
    };
}

interface SwapHarness {
    rail: RailModel;
    live: (index: number) => number;
    setTerm: (index: number | null) => void;
    announce: () => void;
    watchers: () => number;
    setViewport: (index: number, y: number) => void;
}

function swapHarness(prompts: ScannedPrompt[]): SwapHarness {
    const terms = [countingTerm(), countingTerm()];
    let current: number | null = null;
    let listeners: Array<() => void> = [];

    const scan: PromptScanApi = {
        scan: () => prompts.map((p) => ({ ...p })),
        layoutTicks: () => [],
        currentOrdinalFor: () => 0,
    };

    const rail = new RailModel({
        term: () => (current === null ? null : (terms[current]!.term as never)),
        promptScan: () => scan,
        isRule: () => undefined,
        onTerminal: (listener: () => void) => {
            listeners.push(listener);
            return () => {
                listeners = listeners.filter((l) => l !== listener);
            };
        },
    });

    return {
        rail,
        live: (index) => terms[index]!.live(),
        setTerm: (index) => {
            current = index;
        },
        announce: () => {
            for (const l of [...listeners]) l();
        },
        watchers: () => listeners.length,
        setViewport: (index, y) => terms[index]!.setViewport(y),
    };
}

describe('attaching to a terminal that does not exist yet', () => {
    test('a retain taken before the terminal exists attaches on the notice', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        expect(h.live(0)).toBe(0);
        expect(h.rail.prompts.length).toBe(0);

        h.setTerm(0);
        h.announce();
        expect(h.live(0)).toBe(2);
        expect(h.rail.prompts.length).toBe(1);
    });

    test('the viewport is read on that attach, so a page loaded scrolled is right', () => {
        const h = swapHarness([prompt(1, 10, 'first'), prompt(2, 60, 'second')]);
        live = h.rail;
        h.rail.retain();
        h.setViewport(0, 100);
        h.setTerm(0);
        h.announce();
        expect(h.rail.viewportTop).toBe(100);
        expect(h.rail.headerPrompt?.ordinal).toBe(2);
    });

    test('a replacement terminal is listened to and the old one is dropped', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.setTerm(0);
        h.rail.retain();
        expect(h.live(0)).toBe(2);

        h.setTerm(1);
        h.announce();
        expect(h.live(0)).toBe(0);
        expect(h.live(1)).toBe(2);
    });

    test('the panel opening over a swapped terminal attaches to the new one', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.setTerm(0);
        h.rail.retain();
        h.setTerm(1);
        h.rail.show();
        expect(h.live(0)).toBe(0);
        expect(h.live(1)).toBe(2);
    });

    test('NEGATIVE: a notice nobody is holding the model for attaches nothing', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        h.rail.release();
        h.setTerm(0);
        h.announce();
        expect(h.live(0)).toBe(0);
    });

    test('release gives the lifecycle subscription back as well', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        expect(h.watchers()).toBe(1);
        h.rail.release();
        expect(h.watchers()).toBe(0);
    });

    test('NEGATIVE: two holders take ONE lifecycle subscription, not two', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        h.rail.show();
        expect(h.watchers()).toBe(1);
    });

    test('dispose gives it back too', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        h.setTerm(0);
        h.rail.retain();
        h.rail.dispose();
        expect(h.watchers()).toBe(0);
        expect(h.live(0)).toBe(0);
    });

    test('a terminal that went away leaves nothing attached behind it', () => {
        const h = swapHarness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.setTerm(0);
        h.rail.retain();
        h.setTerm(null);
        h.announce();
        expect(h.live(0)).toBe(0);
    });
});
