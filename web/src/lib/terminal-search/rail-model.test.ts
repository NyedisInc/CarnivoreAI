import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { RailModel } from './rail-model.svelte';
import type { DisposableLike, MarkerLike, PromptScanApi, ScannedPrompt } from './types';

/** One scanned prompt, as the scanner reports it. */
function prompt(ordinal: number, line: number, text: string): ScannedPrompt {
    return { ordinal, line, text, full: text, preview: text.slice(0, 80) };
}

interface Harness {
    rail: RailModel;
    live: () => number;
    scrollTo: (y: number) => void;
    setBufferType: (type: string) => void;
    moveMarker: (index: number, line: number) => void;
    setBaseY: (y: number) => void;
}

function harness(prompts: ScannedPrompt[]): Harness {
    const buffer: Record<string, unknown> = {
        type: 'normal',
        baseY: 0,
        cursorY: 0,
        viewportY: 0,
        length: 1000,
    };
    const markers: MarkerLike[] = [];
    let attached = 0;
    let onScroll: (() => void) | null = null;

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

    const term = {
        cols: 80,
        rows: 24,
        get buffer() {
            return { active: buffer };
        },
        registerMarker: (offset: number) => {
            const m: MarkerLike = {
                line: (buffer.baseY as number) + (buffer.cursorY as number) + offset,
                isDisposed: false,
                dispose(this: MarkerLike) {
                    this.isDisposed = true;
                },
            };
            markers.push(m);
            return m;
        },
        scrollToLine: () => {},
        onWriteParsed: () => subscribe(),
        onScroll: (cb: () => void) => {
            onScroll = cb;
            return subscribe();
        },
    };

    const scan: PromptScanApi = {
        scan: () => prompts.map((p) => ({ ...p })),
        layoutTicks: () => [],
        currentOrdinalFor: () => 0,
    };

    const rail = new RailModel({
        term: () => term,
        promptScan: () => scan,
        isRule: () => undefined,
    });

    return {
        rail,
        live: () => attached,
        scrollTo: (y) => {
            buffer.viewportY = y;
            onScroll?.();
        },
        setBufferType: (type) => {
            buffer.type = type;
        },
        moveMarker: (index, line) => {
            const m = markers[index];
            if (m) m.line = line;
        },
        setBaseY: (y) => {
            buffer.baseY = y;
        },
    };
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

describe('keeping the model live without showing the strip', () => {
    test('retain attaches the terminal listeners and scans', () => {
        const h = harness([prompt(1, 10, 'first')]);
        live = h.rail;
        expect(h.live()).toBe(0);
        h.rail.retain();
        expect(h.live()).toBe(2);
        expect(h.rail.prompts.length).toBe(1);
    });

    test('NEGATIVE: retain leaves the STRIP hidden; it is not a show()', () => {
        const h = harness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        expect(h.rail.hidden).toBe(true);
    });

    test('release detaches them again', () => {
        const h = harness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        h.rail.release();
        expect(h.live()).toBe(0);
    });

    test('a hide() while retained keeps the listeners the header needs', () => {
        const h = harness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        h.rail.show();
        h.rail.hide();
        expect(h.live()).toBe(2);
        expect(h.rail.hidden).toBe(true);
    });

    test('two holders, and the LAST one out turns the listeners off', () => {
        const h = harness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        h.rail.retain();
        h.rail.release();
        expect(h.live()).toBe(2);
        h.rail.release();
        expect(h.live()).toBe(0);
    });

    test('NEGATIVE: an unmatched release cannot drive the count below zero', () => {
        const h = harness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.release();
        h.rail.retain();
        expect(h.live()).toBe(2);
    });

    test('dispose drops the listeners whatever is still holding it', () => {
        const h = harness([prompt(1, 10, 'first')]);
        h.rail.retain();
        h.rail.retain();
        h.rail.dispose();
        expect(h.live()).toBe(0);
    });
});

describe('the prompt the header names', () => {
    test('nothing is named while every prompt is still on screen', () => {
        const h = harness([prompt(1, 10, 'first')]);
        live = h.rail;
        h.rail.retain();
        expect(h.rail.headerPrompt).toBe(null);
    });

    test('the last prompt above the viewport is named, with its text', () => {
        const h = harness([prompt(1, 10, 'first'), prompt(2, 60, 'second')]);
        live = h.rail;
        h.rail.retain();
        h.scrollTo(100);
        vi.runAllTimers();
        expect(h.rail.headerPrompt?.ordinal).toBe(2);
        expect(h.rail.headerPrompt?.text).toBe('second');
    });

    test('scrolling further up swaps it for the older prompt', () => {
        const h = harness([prompt(1, 10, 'first'), prompt(2, 60, 'second')]);
        live = h.rail;
        h.rail.retain();
        h.scrollTo(100);
        vi.runAllTimers();
        expect(h.rail.headerPrompt?.ordinal).toBe(2);
        h.scrollTo(40);
        vi.runAllTimers();
        expect(h.rail.headerPrompt?.ordinal).toBe(1);
    });

    test('a marker xterm moved on a trim is followed, not the scanned row', () => {
        const h = harness([prompt(1, 10, 'first'), prompt(2, 600, 'second')]);
        live = h.rail;
        h.rail.retain();
        h.moveMarker(1, 20);
        h.scrollTo(100);
        vi.runAllTimers();
        expect(h.rail.headerPrompt?.ordinal).toBe(2);
    });

    test('NEGATIVE: the alternate screen names nothing', () => {
        const h = harness([prompt(1, 10, 'first'), prompt(2, 60, 'second')]);
        live = h.rail;
        h.rail.retain();
        h.setBufferType('alternate');
        h.rail.refresh();
        expect(h.rail.headerPrompt).toBe(null);
    });

    test('NEGATIVE: a session with no prompts names nothing', () => {
        const h = harness([]);
        live = h.rail;
        h.rail.retain();
        h.scrollTo(900);
        vi.runAllTimers();
        expect(h.rail.headerPrompt).toBe(null);
    });
});

describe('whether the header arrows have somewhere to go', () => {
    function fixture(): Harness {
        return harness([
            prompt(1, 6, 'alpha'),
            prompt(2, 16, 'bravo'),
            prompt(3, 69, 'charlie'),
            prompt(4, 133, 'delta'),
        ]);
    }

    test('NEGATIVE: at charlie, delta cannot reach the top row, so hasNext is false', () => {
        const h = fixture();
        live = h.rail;
        h.setBaseY(98);
        h.rail.retain();
        h.scrollTo(69);
        vi.runAllTimers();
        expect(h.rail.headerPrompt?.ordinal).toBe(3);
        expect(h.rail.headerControls).toEqual({ hasPrev: true, hasNext: false });
    });

    test('at bravo, charlie can still reach the top row, so hasNext is true', () => {
        const h = fixture();
        live = h.rail;
        h.setBaseY(98);
        h.rail.retain();
        h.scrollTo(16);
        vi.runAllTimers();
        expect(h.rail.headerPrompt?.ordinal).toBe(2);
        expect(h.rail.headerControls).toEqual({ hasPrev: true, hasNext: true });
    });

    test('NEGATIVE: no header prompt means neither arrow has anywhere to go', () => {
        const h = fixture();
        live = h.rail;
        h.setBaseY(98);
        h.rail.retain();
        expect(h.rail.headerPrompt).toBe(null);
        expect(h.rail.headerControls).toEqual({ hasPrev: false, hasNext: false });
    });
});
