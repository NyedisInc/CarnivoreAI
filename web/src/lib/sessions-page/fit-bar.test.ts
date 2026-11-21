/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { COMPACT_EXIT_MARGIN_PX, nextCompact, watchBarFit } from './fit-bar';

describe('nextCompact', () => {
    it('goes compact as soon as the labelled row is wider than the bar', () => {
        expect(nextCompact(false, 1065, 1097, false)).toBe(true);
    });
    it('keeps the labels while the labelled row fits', () => {
        expect(nextCompact(false, 1440, 1097, false)).toBe(false);
    });
    it('stays compact inside the exit margin and leaves it past the margin', () => {
        expect(nextCompact(true, 1097 + COMPACT_EXIT_MARGIN_PX - 1, 1097, false)).toBe(true);
        expect(nextCompact(true, 1097 + COMPACT_EXIT_MARGIN_PX, 1097, false)).toBe(false);
    });
    it('is never compact on a phone or before the bar has a width', () => {
        expect(nextCompact(true, 400, 1097, true)).toBe(false);
        expect(nextCompact(false, 0, 1097, false)).toBe(false);
    });
});

function plantBar(widths: { labelled: number; compact: number; end: number }, barWidth: { px: number }) {
    const bar = document.createElement('div');
    const facets = document.createElement('div');
    facets.className = 'oc-toolbar__facets';
    const end = document.createElement('div');
    end.className = 'oc-toolbar__end';
    const state = { compact: false };
    const box = (px: () => number) => ({ getBoundingClientRect: () => ({ width: px() }) as DOMRect });
    for (let i = 0; i < 2; i++) {
        const kid = document.createElement('div');
        Object.assign(kid, box(() => (state.compact ? widths.compact : widths.labelled)));
        facets.append(kid);
    }
    const endKid = document.createElement('div');
    Object.assign(endKid, box(() => widths.end));
    end.append(endKid);
    bar.append(facets, end);
    Object.defineProperty(bar, 'clientWidth', { get: () => barWidth.px });
    return { bar, state };
}

describe('watchBarFit', () => {
    let observe: (() => void) | undefined;
    const stubHost = (fontsReady: Promise<unknown> | null = null): void => {
        vi.stubGlobal('ResizeObserver', class { constructor(cb: () => void) { observe = cb; } observe() {} disconnect() {} });
        vi.stubGlobal('requestAnimationFrame', (cb: () => void) => { cb(); return 1; });
        vi.stubGlobal('cancelAnimationFrame', () => {});
        Object.defineProperty(document, 'fonts', { value: fontsReady ? { ready: fontsReady } : undefined, configurable: true });
        vi.stubGlobal('innerWidth', 1600);
    };
    afterEach(() => vi.unstubAllGlobals());

    it('keeps the labelled need while compact: a wider compact row moves the exit point (no stale width)', () => {
        stubHost();
        const barWidth = { px: 650 };
        const widths = { labelled: 300, compact: 250, end: 100 };
        const { bar, state } = plantBar(widths, barWidth);
        const seen: boolean[] = [];
        watchBarFit(bar, (c) => { state.compact = c; seen.push(c); });
        observe?.();
        expect(seen).toEqual([true]);
        observe?.();
        widths.compact = 280;
        barWidth.px = 720;
        observe?.();
        expect(seen).toEqual([true]);
    });

    it('re-settles once when the fonts finish loading', async () => {
        let ready!: () => void;
        stubHost(new Promise<void>((resolve) => { ready = resolve; }));
        const barWidth = { px: 1000 };
        const { bar, state } = plantBar({ labelled: 300, compact: 250, end: 100 }, barWidth);
        const seen: boolean[] = [];
        watchBarFit(bar, (c) => { state.compact = c; seen.push(c); });
        barWidth.px = 650;
        ready();
        await Promise.resolve();
        await Promise.resolve();
        expect(seen).toEqual([true]);
    });
});
