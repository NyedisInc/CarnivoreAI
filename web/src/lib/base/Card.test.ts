/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import Card from './Card.svelte';
import { cssRules } from './css-rules';

let mounted: Record<string, unknown>[] = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

function card(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    const children = createRawSnippet(() => ({ render: () => '<p>body</p>' }));
    mounted.push(mount(Card, { target, props: { children, ...('untitled' in props ? {} : { title: 'backup' }), ...props } }) as Record<string, unknown>);
    flushSync();
    return target.querySelector('.oc-card')!;
}

test('without onopen the title is plain text, with it the title is a button that calls it once', () => {
    expect(card({}).querySelector('.oc-card__open')).toBeNull();
    const onopen = vi.fn();
    const onclick = vi.fn();
    const el = card({ onopen, onclick });
    const button = el.querySelector<HTMLButtonElement>('button.oc-card__open')!;
    expect(button.textContent).toBe('backup');
    button.click();
    expect(onopen).toHaveBeenCalledTimes(1);
    expect(onclick).not.toHaveBeenCalled();
});

test('a card with no title, lead, actions or fold renders no title strip, only the bordered body, and takes an aria-label', () => {
    const el = card({ untitled: true, 'aria-label': 'one note' });
    expect(el.querySelector('.oc-card__head')).toBeNull();
    expect(el.hasAttribute('aria-labelledby')).toBe(false);
    expect(el.getAttribute('aria-label')).toBe('one note');
    expect(el.querySelector('.oc-card__body')!.textContent).toBe('body');
});

test('a card with a title keeps its strip and labels itself by the title', () => {
    const el = card({});
    expect(el.querySelector('.oc-card__head')).not.toBeNull();
    expect(el.getAttribute('aria-labelledby')).toBe(el.querySelector('.oc-card__title')!.id);
});

test('foldable or onopen with no title fails loudly', () => {
    expect(() => card({ untitled: true, foldable: true })).toThrow(/title/);
    expect(() => card({ untitled: true, onopen: () => {} })).toThrow(/title/);
});

test('the title strip wraps its actions to a second line and the title keeps its width', () => {
    const rules = cssRules(readFileSync(`${process.cwd()}/src/lib/base/card.css`, 'utf8'));
    const by = (sel: string) => rules.find((r) => r.selector === sel)!.decls;
    expect(by('.oc-card__head')['flex-wrap']).toBe('wrap');
    expect(by('.oc-card__head')['min-height']).toContain('--oc-titlerow-h-short');
    expect(by('.oc-card__title')['flex-shrink'] ?? by('.oc-card__title').flex).toMatch(/^0( 0 auto)?$/);
    expect(by('.oc-card__title')['max-width']).toBe('100%');
    expect(by('.oc-card__toggle').flex).toMatch(/^1 0 auto$/);
    expect(by('.oc-card__toggle')['min-width']).toBe('min(12ch, 100%)');
});
