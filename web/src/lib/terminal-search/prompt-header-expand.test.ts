/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

import { t } from '../i18n/index.svelte';
import {
    afterEachHeader,
    beforeEachHeader,
    metrics,
    mounted,
    observers,
} from './prompt-header-harness';
import type { Harness } from './prompt-header-harness';

beforeEach(() => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    beforeEachHeader();
});

afterEach(() => {
    afterEachHeader();
    vi.restoreAllMocks();
});

describe('whether the toggle is there at all', () => {
    test('NEGATIVE: a prompt that fits its line offers no toggle', () => {
        metrics.scrollWidth = 200;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(40);
        expect(h.maybe('more')).toBe(null);
    });

    test('a prompt typed over two lines offers the toggle even when its folded line fits', () => {
        metrics.scrollWidth = 200;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(100);
        expect(h.maybe('more')).not.toBe(null);
    });

    test('a prompt cut off by the line offers one', () => {
        metrics.scrollWidth = 900;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(100);
        expect(h.maybe('more')).not.toBe(null);
    });

    test('the measurement is retaken when the prompt changes', () => {
        metrics.scrollWidth = 900;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(100);
        expect(h.maybe('more')).not.toBe(null);
        metrics.scrollWidth = 100;
        h.scrollTo(40);
        expect(h.maybe('more')).toBe(null);
    });

    test('the measurement is retaken when the strip is resized', () => {
        metrics.scrollWidth = 100;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(40);
        expect(h.maybe('more')).toBe(null);
        metrics.clientWidth = 50;
        observers.at(-1)?.fire();
        flushSync();
        expect(h.maybe('more')).not.toBe(null);
    });

    test('the observer is disconnected when the strip goes away', () => {
        const h = mounted();
        h.scrollTo(100);
        const observer = observers.at(-1);
        expect(observer?.disconnected).toBe(false);
        h.destroy();
        expect(observer?.disconnected).toBe(true);
    });
});

describe('expanding in place', () => {
    function overflowing(): Harness {
        metrics.scrollWidth = 900;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(100);
        return h;
    }

    test('NEGATIVE: the strip shows the folded prompt until it is expanded', () => {
        const h = overflowing();
        expect(h.button('preview').textContent).toBe('first line second line');
    });

    test('the toggle grows the SAME element, with no second copy anywhere', () => {
        const h = overflowing();
        h.button('more').click();
        flushSync();
        const preview = h.button('preview');
        expect(preview.textContent).toBe('first line\nsecond line');
        expect(preview.className).toContain('prompt-header__preview--expanded');
        expect(h.button('more').getAttribute('aria-expanded')).toBe('true');
        const holders = Array.from(document.querySelectorAll('*')).filter(
            (el) => el.children.length === 0
                && el.textContent === 'first line\nsecond line',
        );
        expect(holders).toEqual([preview]);
        expect(document.querySelector('.prompt-header__full')).toBe(null);
    });

    test('the toggle collapses it again', () => {
        const h = overflowing();
        h.button('more').click();
        flushSync();
        h.button('more').click();
        flushSync();
        expect(h.button('preview').textContent).toBe('first line second line');
        expect(h.button('more').getAttribute('aria-expanded')).toBe('false');
    });

    test('escape collapses it and hands the keyboard back to the pane', () => {
        const h = overflowing();
        h.button('more').click();
        flushSync();
        h.button('preview').dispatchEvent(
            new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
        );
        flushSync();
        expect(h.button('preview').textContent).toBe('first line second line');
        expect(h.focused()).toBe(1);
    });

    test('a click outside collapses it and hands the keyboard back', () => {
        const h = overflowing();
        h.button('more').click();
        flushSync();
        document.body.dispatchEvent(new window.MouseEvent('mousedown', { bubbles: true }));
        flushSync();
        expect(h.button('preview').textContent).toBe('first line second line');
        expect(h.focused()).toBe(1);
    });

    test('scrolling to another prompt collapses it', () => {
        const h = overflowing();
        h.button('more').click();
        flushSync();
        h.scrollTo(40);
        expect(h.button('preview').textContent).toBe('run the tests');
        expect(h.button('more')?.getAttribute('aria-expanded')).toBe('false');
    });

    test('a jump collapses it', () => {
        const h = overflowing();
        h.button('more').click();
        flushSync();
        h.button('prev').click();
        flushSync();
        expect(h.button('more').getAttribute('aria-expanded')).toBe('false');
    });
});


describe('the copy the toggle carries', () => {
    test('the toggle says the opposite thing once it is expanded', () => {
        metrics.scrollWidth = 900;
        metrics.clientWidth = 200;
        const h = mounted();
        h.scrollTo(100);
        expect(h.button('more').getAttribute('aria-label')).toBe(t('prompt_header.more'));
        h.button('more').click();
        flushSync();
        const label = h.button('more').getAttribute('aria-label');
        expect(label).toBe(t('prompt_header.less'));
        expect(label).not.toBe('prompt_header.less');
    });
});
