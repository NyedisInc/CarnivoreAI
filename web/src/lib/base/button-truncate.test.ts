/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import Button from './Button.svelte';
import ButtonDynamicLabel from './ButtonDynamicLabel.fixture.svelte';
import { dynamicState } from './button-dynamic-state.svelte';
import { cssRules } from './css-rules';
import { isTruncated, titleWhenTruncated } from './truncate';

const LONG = 'a label far longer than the narrow box around it can ever hold on one line';

let mounted: Record<string, unknown>[] = [];

afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

function measure(scroll: number, client: number): void {
    Object.defineProperty(HTMLElement.prototype, 'scrollWidth', { configurable: true, get: () => scroll });
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => client });
}

function button(text: string): HTMLButtonElement {
    const box = document.createElement('div');
    box.style.width = '80px';
    document.body.append(box);
    const children = createRawSnippet(() => ({ render: () => `<b>${text}</b>` }));
    mounted.push(mount(Button, { target: box, props: { children } }) as Record<string, unknown>);
    flushSync();
    return box.querySelector('button') as HTMLButtonElement;
}

describe('the base button label', () => {
    test('the button never grows past its box and the label clips to one line with an ellipsis', () => {
        const rules = cssRules(readFileSync(resolve(__dirname, 'elements.css'), 'utf8'));
        const of = (selector: string) => rules.find((r) => r.selector.includes(selector))?.decls ?? {};
        expect(of("[data-btn]:not(.xterm *, .cm-editor *)")['max-width']).toBe('100%');
        expect(of("[data-btn]:not(.xterm *, .cm-editor *)")['min-width']).toBe('0');
        const label = of('[data-btn] > [data-btn-label]');
        expect(label.display).toBe('block');
        expect(label['min-width']).toBe('0');
        expect(label.overflow).toBe('hidden');
        expect(label['text-overflow']).toBe('ellipsis');
        expect(label['white-space']).toBe('nowrap');
    });

    test('a label that fits keeps exactly the markup it was written with', () => {
        measure(40, 80);
        const b = button('save');
        expect(b.querySelector('[data-btn-label]')).toBeNull();
        expect(b.querySelector(':scope > b')?.textContent).toBe('save');
    });

    test('a long label in a narrow box gets its full text as the title', () => {
        measure(480, 80);
        const b = button(LONG);
        const label = b.querySelector(':scope > [data-btn-label]') as HTMLElement;
        expect(isTruncated(label)).toBe(true);
        expect(label.querySelector('b')?.textContent).toBe(LONG);
        expect(b.getAttribute('title')).toBe(LONG);
    });

    test('a short label gets no title', () => {
        measure(40, 80);
        const b = button('save');
        expect(b.hasAttribute('title')).toBe(false);
    });

    test('a title the author wrote is kept while the label fits and put back when it stops being cut', async () => {
        measure(480, 80);
        const el = document.createElement('button');
        el.title = 'authored';
        el.innerHTML = `<span data-btn-label>${LONG}</span>`;
        document.body.append(el);
        const action = titleWhenTruncated(el);
        expect(el.title).toBe(LONG);
        measure(40, 80);
        el.firstElementChild!.textContent = 'short';
        await Promise.resolve();
        expect(el.title).toBe('authored');
        action.destroy();
    });

    test('a button with no author title loses the title again once the label fits', async () => {
        measure(480, 80);
        const el = document.createElement('button');
        el.innerHTML = `<span data-btn-label>${LONG}</span>`;
        document.body.append(el);
        const action = titleWhenTruncated(el);
        expect(el.hasAttribute('title')).toBe(true);
        measure(40, 80);
        el.firstElementChild!.textContent = 'short';
        await Promise.resolve();
        expect(el.hasAttribute('title')).toBe(false);
        action.destroy();
    });

    test('a cut label holding an {#if} and an {#each} keeps following its state after the lazy wrap', async () => {
        measure(480, 80);
        const state = dynamicState();
        const box = document.createElement('div');
        document.body.append(box);
        mounted.push(mount(ButtonDynamicLabel, { target: box, props: { state } }) as Record<string, unknown>);
        flushSync();
        const b = box.querySelector('button') as HTMLButtonElement;
        const label = (): HTMLElement => b.querySelector(':scope > [data-btn-label]') as HTMLElement;
        await Promise.resolve();
        expect(label(), 'the cut label was wrapped').not.toBeNull();
        expect(b.querySelectorAll('[data-btn-label]').length).toBe(1);
        const items = () => [...label().querySelectorAll('[data-item]')].map((n) => n.textContent?.trim());
        expect(items()).toEqual(['alpha', 'beta']);

        state.flag = true;
        state.items = ['alpha', 'beta', 'gamma', 'delta'];
        flushSync();
        await Promise.resolve();
        expect(label().querySelectorAll('[data-if]').length).toBe(1);
        expect(items()).toEqual(['alpha', 'beta', 'gamma', 'delta']);
        expect(b.querySelectorAll('[data-if], [data-item]').length).toBe(5);
        expect(b.querySelectorAll('[data-btn-label]').length).toBe(1);
        expect(b.getAttribute('title')).toBe('flagged alpha beta gamma delta');

        state.flag = false;
        state.items = ['beta'];
        flushSync();
        await Promise.resolve();
        expect(label().querySelectorAll('[data-if]').length).toBe(0);
        expect(items()).toEqual(['beta']);
        expect(b.querySelectorAll('[data-if], [data-item]').length).toBe(1);
        expect(b.getAttribute('title')).toBe('beta');
    });
});
