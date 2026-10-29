/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { t } from '../i18n/index.svelte';
import {
    afterEachHeader,
    beforeEachHeader,
    metrics,
    mounted,
    scannedPrompt,
} from './prompt-header-harness';

beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    beforeEachHeader();
});

afterEach(() => {
    afterEachHeader();
    vi.restoreAllMocks();
});

describe('when the strip is on screen at all', () => {
    test('NEGATIVE: nothing has scrolled above the viewport, so it is hidden', () => {
        const h = mounted();
        expect(h.strip().hidden).toBe(true);
    });

    test('a prompt scrolled above brings the strip up with its preview', () => {
        const h = mounted();
        h.scrollTo(100);
        expect(h.strip().hidden).toBe(false);
        expect(h.button('preview').textContent).toContain('first line second line');
    });

    test('scrolling further up swaps it for the older prompt', () => {
        const h = mounted();
        h.scrollTo(100);
        expect(h.button('preview').textContent).toContain('first line');
        h.scrollTo(40);
        expect(h.button('preview').textContent).toContain('run the tests');
    });

    test('NEGATIVE: a session with no prompts never shows the strip', () => {
        const h = mounted([]);
        h.scrollTo(900);
        expect(h.strip().hidden).toBe(true);
    });
});

describe('moving between prompts', () => {
    test('clicking the preview jumps to the prompt it names', () => {
        const h = mounted();
        h.scrollTo(100);
        h.button('preview').click();
        expect(h.scrolled).toEqual([60]);
    });

    test('the up control jumps to the PREVIOUS prompt, ordinal minus one', () => {
        const h = mounted();
        h.scrollTo(100);
        h.button('prev').click();
        expect(h.scrolled).toEqual([10]);
    });

    test('the down control jumps to the NEXT prompt, ordinal plus one', () => {
        const h = mounted();
        h.scrollTo(100);
        h.button('next').click();
        expect(h.scrolled).toEqual([120]);
    });

    test('NEGATIVE: the up control is disabled on the first prompt', () => {
        const h = mounted();
        h.scrollTo(40);
        expect(h.button('prev').disabled).toBe(true);
        expect(h.button('next').disabled).toBe(false);
    });

    test('NEGATIVE: the down control is disabled on the last prompt', () => {
        const h = mounted();
        h.scrollTo(900);
        expect(h.button('next').disabled).toBe(true);
        expect(h.button('prev').disabled).toBe(false);
    });
});

describe('whether the down arrow can reach the newest prompt', () => {
    const FOUR = [
        scannedPrompt(1, 6, ['alpha']),
        scannedPrompt(2, 16, ['bravo']),
        scannedPrompt(3, 69, ['charlie']),
        scannedPrompt(4, 133, ['delta']),
    ];

    test('NEGATIVE: at charlie the down arrow is disabled and a click does nothing', () => {
        const h = mounted(FOUR);
        h.setBaseY(98);
        h.scrollTo(69);
        expect(h.button('preview').textContent).toContain('charlie');
        expect(h.button('next').disabled).toBe(true);
        h.button('next').click();
        expect(h.scrolled).toEqual([]);
    });

    test('at bravo the down arrow still reaches charlie', () => {
        const h = mounted(FOUR);
        h.setBaseY(98);
        h.scrollTo(16);
        expect(h.button('next').disabled).toBe(false);
        h.button('next').click();
        expect(h.scrolled).toEqual([69]);
    });
});

describe('the pane keeps the keyboard', () => {
    test('NEGATIVE: a mouse press on a control never moves focus out of the pane', () => {
        const h = mounted();
        h.scrollTo(100);
        for (const name of ['preview', 'prev', 'next']) {
            const event = new window.MouseEvent('mousedown', {
                bubbles: true,
                cancelable: true,
            });
            h.button(name).dispatchEvent(event);
            expect(event.defaultPrevented).toBe(true);
        }
    });

    test('NEGATIVE: the strip exposes nothing that can write to the pane', () => {
        const h = mounted();
        h.scrollTo(100);
        const writable = h.strip().querySelectorAll('input, textarea, [contenteditable]');
        expect(writable.length).toBe(0);
    });
});

describe('the copy comes from the catalog', () => {
    test('every control label is a resolved catalog string, not a key', () => {
        metrics.scrollWidth = 900;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(100);
        for (const [name, key] of [
            ['prev', 'prompt_header.previous'],
            ['next', 'prompt_header.next'],
            ['more', 'prompt_header.more'],
        ] as const) {
            const label = h.button(name).getAttribute('aria-label');
            expect(label).toBe(t(key));
            expect(label).not.toBe(key);
        }
    });
});

describe('the rail it reads', () => {
    test('the header keeps the model scanning, and lets go when unmounted', () => {
        const h = mounted();
        h.scrollTo(100);
        expect(h.rail.headerPrompt?.ordinal).toBe(2);
        h.destroy();
        expect(h.rail.prompts.length).toBe(0);
    });
});
