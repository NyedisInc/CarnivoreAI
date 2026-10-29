/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { createRawSnippet } from 'svelte';

import MenuItem from './MenuItem.svelte';
import { cleanup, show } from './test-helpers';

afterEach(cleanup);

const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));
const item = (props: Record<string, unknown> = {}) => show(MenuItem, { label: 'add to home', ...props }).querySelector('button')!;

describe('MenuItem', () => {
    test('a menuitem button in the item menu row look: icon, label and key spans, nothing else by default', () => {
        const el = item();
        expect(el.type).toBe('button');
        expect(el.getAttribute('role')).toBe('menuitem');
        expect(el.getAttribute('tabindex')).toBe('-1');
        expect(el.className).toBe('session-row-menu__item');
        expect([...el.children].map((c) => c.className)).toEqual(['session-row-menu__icon', 'session-row-menu__label', 'session-row-menu__key']);
        expect(el.querySelector('.session-row-menu__label')!.textContent).toBe('add to home');
    });

    test('icon snippet, key word and reason line land in their spans', () => {
        const el = item({ icon: html('<i>g</i>'), keyHint: 'chat', reason: 'needs a drive' });
        expect(el.querySelector('.session-row-menu__icon i')?.textContent).toBe('g');
        expect(el.querySelector('.session-row-menu__key')!.textContent).toBe('chat');
        expect(el.querySelector('.session-row-menu__reason')!.textContent).toBe('needs a drive');
    });

    test('disabled is aria-disabled (still focusable), never the disabled attribute, and the reason moves to the tooltip', () => {
        const el = item({ disabled: true, reason: 'already here' });
        expect(el.getAttribute('aria-disabled')).toBe('true');
        expect(el.hasAttribute('disabled')).toBe(false);
        expect(el.getAttribute('data-tooltip')).toBe('already here');
        expect(el.getAttribute('aria-description')).toBe('already here');
        expect(el.querySelector('.session-row-menu__reason')).toBeNull();
    });

    test('a click runs onclick', () => {
        const onclick = vi.fn();
        item({ onclick }).click();
        expect(onclick).toHaveBeenCalledTimes(1);
    });
});
