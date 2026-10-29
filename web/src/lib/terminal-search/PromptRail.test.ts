/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import PromptRail from './PromptRail.svelte';
import { RailModel } from './rail-model.svelte';
import type { MarkerLike, PromptScanApi, ScannedPrompt } from './types';

const realScan: PromptScanApi = (() => {
    const read = (name: string) =>
        fs.readFileSync(
            path.resolve(process.cwd(), '..', 'client', 'js', name),
            'utf8',
        );
    const src = read('terminal-prompt-join.js') + '\n' + read('terminal-prompt-ticks.js') + '\n' + read('terminal-prompt-scan.js');
    const target: Record<string, unknown> = {};
    new Function('window', src)(target);
    return target.TerminalPromptScan as PromptScanApi;
})();

function prompt(ordinal: number, line: number, text: string): ScannedPrompt {
    return { ordinal, line, text, full: text, preview: text.slice(0, 80) };
}

function marker(line: number): MarkerLike {
    return {
        line,
        isDisposed: false,
        dispose(this: MarkerLike) {
            this.isDisposed = true;
        },
    };
}

interface Harness {
    rail: RailModel;
    el: HTMLElement;
    ticks: () => HTMLButtonElement[];
    markers: MarkerLike[];
    offsets: number[];
    scrolled: number[];
    setBuffer: (patch: Record<string, unknown>) => void;
    clickStrip: (x: number, y: number) => void;
    destroy: () => void;
}

const STRIP_LEFT = 40;
const STRIP_TOP = 160;
const STRIP_WIDTH = 24;

function mountRail(prompts: ScannedPrompt[], height = 400): Harness {
    const buffer: Record<string, unknown> = {
        type: 'normal',
        baseY: 100,
        cursorY: 5,
        viewportY: 0,
        length: 1000,
    };
    const markers: MarkerLike[] = [];
    const offsets: number[] = [];
    const scrolled: number[] = [];
    const term = {
        cols: 80,
        rows: 24,
        get buffer() {
            return { active: buffer };
        },
        registerMarker: (offset: number) => {
            offsets.push(offset);
            const m = marker(
                (buffer.baseY as number) + (buffer.cursorY as number) + offset,
            );
            markers.push(m);
            return m;
        },
        scrollToLine: (line: number) => scrolled.push(line),
    };
    const rail = new RailModel({
        term: () => term,
        promptScan: () => ({ ...realScan, scan: () => prompts.map((p) => ({ ...p })) }),
        isRule: () => undefined,
    });

    const target = document.createElement('div');
    document.body.appendChild(target);
    const instance = mount(PromptRail, { target, props: { rail } });
    flushSync();
    const el = target.querySelector('.terminal-prompt-rail') as HTMLElement;
    Object.defineProperty(el, 'clientHeight', { value: height, configurable: true });
    el.getBoundingClientRect = () =>
        ({
            top: STRIP_TOP,
            left: STRIP_LEFT,
            right: STRIP_LEFT + STRIP_WIDTH,
            bottom: STRIP_TOP + height,
            width: STRIP_WIDTH,
            height,
            x: STRIP_LEFT,
            y: STRIP_TOP,
            toJSON: () => ({}),
        }) as DOMRect;
    rail.show();
    flushSync();

    return {
        rail,
        el,
        ticks: () => Array.from(el.querySelectorAll('.prompt-tick')),
        markers,
        offsets,
        scrolled,
        setBuffer: (patch) => Object.assign(buffer, patch),
        clickStrip: (x, y) =>
            el.dispatchEvent(
                new window.MouseEvent('click', {
                    bubbles: true,
                    cancelable: true,
                    clientX: STRIP_LEFT + x,
                    clientY: STRIP_TOP + y,
                }),
            ),
        destroy: () => {
            rail.dispose();
            unmount(instance, { outro: false });
            target.remove();
        },
    };
}

let live: Harness | null = null;

function mounted(prompts: ScannedPrompt[], height?: number): Harness {
    const h = mountRail(prompts, height);
    live = h;
    return h;
}

function nth<T>(list: T[], index: number, what: string): T {
    const value = list[index];
    if (value === undefined) throw new Error(`no ${what} at index ${index}`);
    return value;
}

beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
    live?.destroy();
    live = null;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('painting the strip', () => {
    test('one tick per prompt when the strip has room for them', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 200, 'two'), prompt(3, 900, 'three')]);
        expect(h.ticks()).toHaveLength(3);
        expect(h.el.hidden).toBe(false);
    });

    test('a marker is registered at line minus baseY minus cursorY', () => {
        const h = mounted([prompt(1, 10, 'one')]);
        expect(h.offsets).toEqual([10 - 100 - 5]);
    });

    test('the tooltip reads "#n of N" and carries the preview', () => {
        const h = mounted([prompt(1, 10, 'run the tests'), prompt(2, 500, 'ship it')]);
        expect(nth(h.ticks(), 0, 'tick').getAttribute('title')).toBe('#1 of 2  run the tests');
        expect(nth(h.ticks(), 0, 'tick').getAttribute('aria-label')).toBe('#1 of 2  run the tests');
    });

    test('a cluster names its RANGE and is marked as one', () => {
        const h = mounted(
            [10, 20, 30, 40, 50, 60].map((line, i) => prompt(i + 1, line, `p${i + 1}`)),
            12,
        );
        const ticks = h.ticks();
        expect(ticks).toHaveLength(3);
        expect(nth(ticks, 0, 'tick').classList.contains('is-cluster')).toBe(true);
        expect(nth(ticks, 0, 'tick').getAttribute('title')).toContain('#1-#2 of 6');
    });

    test('NEGATIVE: a roomy strip produces no clusters at all', () => {
        const h = mounted(
            [10, 200, 400, 600, 800, 900].map((line, i) => prompt(i + 1, line, `p${i + 1}`)),
            400,
        );
        expect(h.ticks().every((t) => !t.classList.contains('is-cluster'))).toBe(true);
    });
});

describe('the filter', () => {
    test('a filter DIMS the misses and never removes them', () => {
        const h = mounted([prompt(1, 10, 'alpha'), prompt(2, 500, 'beta')]);
        h.rail.setFilter((text) => text.includes('alpha'));
        flushSync();
        const ticks = h.ticks();
        expect(ticks).toHaveLength(2);
        expect(nth(ticks, 0, 'tick').classList.contains('is-dim')).toBe(false);
        expect(nth(ticks, 1, 'tick').classList.contains('is-dim')).toBe(true);
    });

    test('clearing the filter lights everything back up', () => {
        const h = mounted([prompt(1, 10, 'alpha'), prompt(2, 500, 'beta')]);
        h.rail.setFilter((text) => text.includes('alpha'));
        flushSync();
        h.rail.setFilter(null);
        flushSync();
        expect(h.ticks().every((t) => !t.classList.contains('is-dim'))).toBe(true);
    });

    test('a filter that throws is treated as a match, not as a miss', () => {
        const h = mounted([prompt(1, 10, 'alpha')]);
        h.rail.setFilter(() => {
            throw new Error('half-typed');
        });
        flushSync();
        expect(nth(h.ticks(), 0, 'tick').classList.contains('is-dim')).toBe(false);
    });
});

describe('where you are', () => {
    test('the viewport row picks the current tick', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 500, 'two'), prompt(3, 900, 'three')]);
        h.rail.setViewport(600);
        flushSync();
        const current = h.ticks().filter((t) => t.classList.contains('is-current'));
        expect(current).toHaveLength(1);
        expect(nth(current, 0, 'current tick').getAttribute('data-ordinal')).toBe('2');
    });
});

describe('jumping', () => {
    test('a jump calls scrollToLine with the ABSOLUTE line', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 500, 'two')]);
        expect(h.rail.jumpTo(2)).toBe(true);
        expect(h.scrolled).toEqual([500]);
    });

    test('clicking a tick jumps to it', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 500, 'two')]);
        nth(h.ticks(), 1, 'tick').click();
        expect(h.scrolled).toEqual([500]);
    });

    test('a marker xterm moved on a trim is followed, not the scanned row', () => {
        const h = mounted([prompt(1, 10, 'one')]);
        nth(h.markers, 0, 'marker').line = 4;
        h.rail.jumpTo(1);
        expect(h.scrolled).toEqual([4]);
    });

    test('NEGATIVE: a prompt whose marker was disposed refuses the jump', () => {
        const h = mounted([prompt(1, 10, 'one')]);
        nth(h.markers, 0, 'marker').dispose?.();
        expect(h.rail.jumpTo(1)).toBe(false);
        expect(h.scrolled).toEqual([]);
    });

    test('a click on the EMPTY STRIP beside a tick jumps to that tick', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 500, 'two'), prompt(3, 900, 'three')]);
        const second = nth(h.rail.tickViews, 1, 'tick view');
        h.clickStrip(STRIP_WIDTH - 15, second.y);
        expect(h.scrolled).toEqual([500]);
    });

    test('the strip picks the NEAREST tick, not the first or the last', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 500, 'two'), prompt(3, 900, 'three')]);
        const views = h.rail.tickViews;
        const third = nth(views, 2, 'tick view');
        const second = nth(views, 1, 'tick view');
        h.clickStrip(4, third.y - Math.floor((third.y - second.y) / 4));
        expect(h.scrolled).toEqual([900]);
    });

    test('a click on the TICK jumps exactly once, not twice', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 500, 'two')]);
        nth(h.ticks(), 1, 'tick').click();
        expect(h.scrolled).toEqual([500]);
    });

    test('NEGATIVE: a strip with no ticks refuses the click rather than jumping', () => {
        const h = mounted([]);
        h.clickStrip(4, 120);
        expect(h.scrolled).toEqual([]);
    });

    test('the offset is measured from the STRIP, not read off clientY raw', () => {
        const h = mounted([prompt(1, 10, 'one'), prompt(2, 500, 'two'), prompt(3, 900, 'three')]);
        const views = h.rail.tickViews;
        const first = nth(views, 0, 'tick view');
        const second = nth(views, 1, 'tick view');
        expect(first.y + STRIP_TOP).toBeGreaterThan((first.y + second.y) / 2);
        h.clickStrip(4, first.y);
        expect(h.scrolled).toEqual([10]);
    });

    test('jump walks only the MATCHING prompts, and wraps', () => {
        const h = mounted([
            prompt(1, 10, 'alpha'),
            prompt(2, 300, 'beta'),
            prompt(3, 600, 'alpha again'),
        ]);
        h.rail.setFilter((text) => text.includes('alpha'));
        h.rail.setViewport(0);
        flushSync();
        h.rail.jump(1);
        h.rail.jump(1);
        expect(h.scrolled).toEqual([600, 10]);
    });
});

describe('when there is nothing to show', () => {
    test('an empty scan hides the strip', () => {
        const h = mounted([]);
        expect(h.el.hidden).toBe(true);
        expect(h.ticks()).toHaveLength(0);
    });

    test('the alternate screen hides it, prompts or not', () => {
        const h = mounted([prompt(1, 10, 'one')]);
        expect(h.el.hidden).toBe(false);
        h.setBuffer({ type: 'alternate' });
        h.rail.refresh();
        flushSync();
        expect(h.el.hidden).toBe(true);
    });

    test('hide() puts it away and dispose() releases every marker', () => {
        const h = mounted([prompt(1, 10, 'one')]);
        h.rail.hide();
        flushSync();
        expect(h.el.hidden).toBe(true);
        h.rail.dispose();
        expect(h.markers.every((m) => m.isDisposed)).toBe(true);
    });
});
