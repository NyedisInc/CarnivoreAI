/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync } from 'svelte';
import InfoTip from './InfoTip.svelte';
import { cleanup, press, show } from '../base/test-helpers';

afterEach(cleanup);

const tip = () => {
    const root = show(InfoTip, { text: 'a note', label: 'what is this' });
    return { root, btn: root.querySelector<HTMLButtonElement>('button')! };
};

describe('InfoTip', () => {
    test('aria-expanded flips with the note, aria-pressed is never set, and the open look is data-active', () => {
        const { root, btn } = tip();
        expect(btn.getAttribute('aria-expanded')).toBe('false');
        expect(btn.hasAttribute('aria-pressed')).toBe(false);
        expect(btn.hasAttribute('data-active')).toBe(false);
        btn.click();
        flushSync();
        expect(btn.getAttribute('aria-expanded')).toBe('true');
        expect(btn.hasAttribute('aria-pressed')).toBe(false);
        expect(btn.hasAttribute('data-active')).toBe(true);
        expect(root.querySelector('[role="note"]')?.textContent).toBe('a note');
        press(btn, 'Escape');
        flushSync();
        expect(btn.getAttribute('aria-expanded')).toBe('false');
        expect(btn.hasAttribute('data-active')).toBe(false);
    });

    test('the hover tip is the note, not the label', () => {
        expect(tip().btn.getAttribute('title')).toBe('a note');
        expect(tip().btn.getAttribute('aria-label')).toBe('what is this');
    });
});
