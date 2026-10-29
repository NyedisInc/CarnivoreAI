/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import List from './List.svelte';

let mounted: Record<string, unknown>[] = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));

function list(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(List, { target, props: { children: html('<div class="oc-list__row">a</div>'), ...props } }) as Record<string, unknown>);
    flushSync();
    return target.querySelector('.oc-list')!;
}

test('a list with the default density and the list role', () => {
    const el = list({ label: 'recent runs' });
    expect(el.getAttribute('role')).toBe('list');
    expect(el.getAttribute('aria-label')).toBe('recent runs');
    expect(el.dataset.density).toBe('default');
    expect(el.querySelector('.oc-list__row')?.textContent).toBe('a');
});

test('density, role, class and attributes pass through', () => {
    const el = list({ density: 'dense', role: 'grid', class: 'mine', tabindex: 0, 'data-x': '1' });
    expect(el.dataset.density).toBe('dense');
    expect(el.getAttribute('role')).toBe('grid');
    expect(el.className).toBe('oc-list mine');
    expect(el.tabIndex).toBe(0);
    expect(el.dataset.x).toBe('1');
});
