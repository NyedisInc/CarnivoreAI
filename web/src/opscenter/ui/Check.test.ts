/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync } from 'svelte';

import Check from './Check.svelte';
import { cleanup, show } from '../../lib/base/test-helpers';

afterEach(cleanup);

const check = (props: Record<string, unknown>): HTMLButtonElement =>
    show(Check, { label: 'agents', checked: false, onToggle: () => {}, ...props }).querySelector('button')!;

describe('Check over Switch', () => {
    test('role checkbox by default, switch on request, aria-label, id and data-* on the button', () => {
        const el = check({ ariaLabel: 'show agents', id: 'c1', 'data-probe': '7' });
        expect(el.classList.contains('oc-check')).toBe(true);
        expect(el.getAttribute('role')).toBe('checkbox');
        expect(el.getAttribute('aria-label')).toBe('show agents');
        expect(el.id).toBe('c1');
        expect(el.dataset.probe).toBe('7');
        expect(check({ role: 'switch' }).getAttribute('role')).toBe('switch');
    });

    test('a click asks onToggle for the other state; a refused change leaves the check where it was', () => {
        const seen: boolean[] = [];
        const el = check({ onToggle: (next: boolean) => seen.push(next) });
        el.click();
        flushSync();
        expect(seen).toEqual([true]);
        expect(el.getAttribute('aria-checked')).toBe('false');
    });

    test('glyph, hint, note and bare render as before', () => {
        const el = check({ glyph: 'bell', hint: 'quiet line', note: 'new', bare: true, checked: true });
        expect(el.getAttribute('aria-checked')).toBe('true');
        expect(el.querySelector('.oc-check__glyph svg')).not.toBeNull();
        expect(el.querySelector('.oc-check__hint')?.textContent).toBe('quiet line');
        expect(el.querySelector('.oc-check__note')?.textContent).toBe('new');
        expect(el.classList.contains('oc-check--bare')).toBe(true);
    });
});
