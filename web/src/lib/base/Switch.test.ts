/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync } from 'svelte';

import Switch from './Switch.svelte';
import { cleanup, show } from './test-helpers';

afterEach(cleanup);

const sw = (props: Record<string, unknown> = {}): HTMLButtonElement =>
    show(Switch, { label: 'sounds', ...props }).querySelector('button')!;

describe('Switch', () => {
    test('a native button with role switch, aria-checked and the label', () => {
        const el = sw();
        expect(el.tagName).toBe('BUTTON');
        expect(el.type).toBe('button');
        expect(el.getAttribute('role')).toBe('switch');
        expect(el.getAttribute('aria-checked')).toBe('false');
        expect(el.textContent?.trim()).toBe('sounds');
        expect(el.classList.contains('oc-check')).toBe(true);
        expect(el.querySelector('.oc-check__box')?.getAttribute('aria-hidden')).toBe('true');
    });

    test('a click flips aria-checked and reports the new state', () => {
        const seen: boolean[] = [];
        const el = sw({ onchange: (next: boolean) => seen.push(next) });
        el.click();
        flushSync();
        expect(el.getAttribute('aria-checked')).toBe('true');
        el.click();
        flushSync();
        expect(el.getAttribute('aria-checked')).toBe('false');
        expect(seen).toEqual([true, false]);
    });

    test('disabled does not toggle', () => {
        const seen: boolean[] = [];
        const el = sw({ disabled: true, onchange: (next: boolean) => seen.push(next) });
        el.click();
        flushSync();
        expect(el.disabled).toBe(true);
        expect(seen).toEqual([]);
    });

    test('hint, note, bare and pass-through attributes', () => {
        const el = sw({ checked: true, hint: 'plays a tone', note: 'new', 'data-probe': '1', 'aria-describedby': 'why' });
        expect(el.getAttribute('aria-checked')).toBe('true');
        expect(el.querySelector('.oc-check__hint')?.textContent).toBe('plays a tone');
        expect(el.querySelector('.oc-check__note')?.textContent).toBe('new');
        expect(el.dataset.probe).toBe('1');
        expect(el.getAttribute('aria-describedby')).toBe('why');
        expect(el.classList.contains('oc-check--bare')).toBe(false);
        expect(sw({ bare: true }).classList.contains('oc-check--bare')).toBe(true);
        expect(sw({ label: '', 'aria-label': 'sounds' }).classList.contains('oc-check--bare')).toBe(true);
    });
    test('role checkbox announces a set member in the same look; glyph draws its icon', () => {
        const el = sw({ role: 'checkbox', glyph: 'bell' });
        expect(el.getAttribute('role')).toBe('checkbox');
        expect(el.classList.contains('oc-check')).toBe(true);
        expect(el.querySelector('.oc-check__glyph svg')).not.toBeNull();
        expect(sw().querySelector('.oc-check__glyph')).toBeNull();
    });
});
