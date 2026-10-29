/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import Toolbar from './Toolbar.svelte';
import { cssRules } from './css-rules';

const toolbarCss = readFileSync(`${process.cwd()}/src/lib/base/toolbar.css`, 'utf8');

let mounted: Record<string, unknown>[] = [];
afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

const html = (markup: string) => createRawSnippet(() => ({ render: () => markup }));

function bar(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(Toolbar, { target, props }) as Record<string, unknown>);
    flushSync();
    return target.querySelector('.oc-toolbar')!;
}

test('every slot in the fixed order, each in its wrapper', () => {
    const el = bar({
        label: 'automations list',
        search: html('<input type="search" />'),
        filters: html('<span>f</span>'),
        extras: html('<span>x</span>'),
        end: html('<span>3 of 9</span>'),
        below: html('<span>pill</span>'),
    });
    expect(el.getAttribute('role')).toBe('toolbar');
    expect(el.getAttribute('aria-label')).toBe('automations list');
    expect([...el.children].map((c) => c.className)).toEqual([
        'oc-toolbar__search', 'oc-toolbar__facets', 'oc-toolbar__extras', 'oc-toolbar__end', 'oc-toolbar__below',
    ]);
    expect(el.querySelector('.oc-toolbar__end')?.textContent).toBe('3 of 9');
});

test('a slot left out draws nothing; band, wrap, role, class and attributes', () => {
    const el = bar({ end: html('<span>n</span>'), band: true, wrap: true, role: 'search', class: 'ap-lt', 'data-auto-toolbar': '' });
    expect([...el.children].map((c) => c.className)).toEqual(['oc-toolbar__end']);
    expect(el.className).toBe('oc-toolbar oc-toolbar--band oc-toolbar--wrap ap-lt');
    expect(el.getAttribute('role')).toBe('search');
    expect(el.hasAttribute('data-auto-toolbar')).toBe(true);
    expect(bar({}).className).toBe('oc-toolbar');
});

test('a phone scrolls a plain bar sideways and leaves a --wrap bar wrapping', () => {
    const phone = cssRules(toolbarCss).filter((r) => r.within.some((w) => w.includes('max-width: 767px')));
    const scroll = phone.find((r) => r.decls['overflow-x'] === 'auto');
    expect(scroll?.selector).toBe('.oc-toolbar:not(.oc-toolbar--wrap)');
    expect(scroll?.decls['flex-wrap']).toBe('nowrap');
    expect(phone.every((r) => r.selector.includes(':not(.oc-toolbar--wrap)'))).toBe(true);
});
