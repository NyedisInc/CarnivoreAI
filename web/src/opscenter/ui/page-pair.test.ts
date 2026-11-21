/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import type { Snippet } from 'svelte';
import Page from './Page.svelte';
import { menuPageState } from '../../lib/menu-page/menu-page-shell.svelte';
import { viewport } from '../engine/viewport.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (app) unmount(app);
    app = null;
    document.body.replaceChildren();
    menuPageState.surface = false;
    viewport.narrow = false;
});

/** A snippet that draws one fixed fragment. Inputs: html (str). Output: Snippet. */
const snip = (html: string): Snippet => createRawSnippet(() => ({ render: () => html }));

function show(props: Record<string, unknown>): HTMLElement {
    const host = document.createElement('div');
    host.id = 'settings-screen';
    document.body.append(host);
    app = mount(Page, {
        target: host,
        props: { title: 'settings', frame: 'nav', scroll: 'self', pair: true, side: snip('<nav id="rail">rail</nav>'), tabs: snip('<i id="tabs">tabs</i>'), children: snip('<p id="body">body</p>'), ...props },
    });
    flushSync();
    return host;
}

const roots = (host: HTMLElement): HTMLElement[] => [...host.children].filter((n): n is HTMLElement => n.classList.contains('oc-page'));

test('at drawer widths the pair is a list drawer and, while open, a page drawer beside it', () => {
    menuPageState.surface = true;
    let pairClosed = 0;
    const host = show({ pairOpen: true, pairTitle: 'appearance', onPairClose: () => pairClosed++ });
    const [list, page, extra] = roots(host) as [HTMLElement, HTMLElement, HTMLElement | undefined];
    expect(extra).toBeUndefined();
    expect(list.classList.contains('oc-page--drawer-list')).toBe(true);
    expect(list.dataset.pair).toBe('list');
    expect(list.querySelector('.oc-page__frame[data-pair] > [data-frame-region=side] #rail')).not.toBeNull();
    expect(list.querySelector('.oc-page__col, .oc-page__resize, #body')).toBeNull();
    expect(list.querySelector('.oc-titlebar__title')?.textContent).toBe('settings');
    expect(page.classList.contains('oc-page--drawer-stacked')).toBe(true);
    expect(page.dataset.pair).toBe('page');
    expect(page.getAttribute('style')).toContain('--oc-drawer-offset');
    expect(page.querySelector('[data-frame-region=side]')).toBeNull();
    expect(page.querySelector('.oc-page__frame[data-pair] > .oc-page__col [data-frame-region=tabs] #tabs')).not.toBeNull();
    expect(page.querySelector('.oc-page__col [data-frame-region=body] .oc-page__fill #body')).not.toBeNull();
    expect(page.querySelector('.oc-page__resize')).not.toBeNull();
    expect(page.querySelector('.oc-titlebar__title')?.textContent).toBe('appearance');
    (page.querySelector('[data-drawer-close]') as HTMLElement).click();
    expect(pairClosed).toBe(1);
});

test('at drawer widths a closed pair draws the list drawer alone', () => {
    menuPageState.surface = true;
    const host = show({ pairOpen: false, pairTitle: 'appearance' });
    expect(roots(host).map((r) => r.dataset.pair)).toEqual(['list']);
    expect(host.querySelector('#body')).toBeNull();
});

test('with no surface the pair is one nav page, side beside column, and never folds its side into the picker', () => {
    const host = show({ pairOpen: false });
    const [one, extra] = roots(host) as [HTMLElement, HTMLElement | undefined];
    expect(extra).toBeUndefined();
    expect(one.dataset.pair).toBe('one');
    expect(one.classList.contains('oc-page--drawer-list') || one.classList.contains('oc-page--drawer-stacked')).toBe(false);
    expect(one.querySelector('.oc-page__frame[data-pair] > [data-frame-region=side] #rail')).not.toBeNull();
    expect(one.querySelector('.oc-page__frame[data-pair] > .oc-page__col [data-frame-region=body] #body')).not.toBeNull();
    expect(one.querySelector('.oc-page__picker')).toBeNull();
});

test('a nav page without pair is unchanged: no pair marker, and its side still has the phone picker', () => {
    const host = show({ pair: false });
    const [one] = roots(host) as [HTMLElement];
    expect(one.dataset.pair).toBeUndefined();
    expect(one.querySelector('.oc-page__frame')?.hasAttribute('data-pair')).toBe(false);
    expect(one.querySelector('.oc-page__picker')).not.toBeNull();
});

test('a live shrink to phone width with the surface still set collapses the pair to one nav page with its side and search', () => {
    menuPageState.surface = true;
    const host = show({ pairOpen: true, pairTitle: 'appearance', search: snip('<input id="omni">') });
    expect(roots(host).map((r) => r.dataset.pair)).toEqual(['list', 'page']);
    viewport.narrow = true;
    flushSync();
    const [one, extra] = roots(host) as [HTMLElement, HTMLElement | undefined];
    expect(extra).toBeUndefined();
    expect(one.dataset.pair).toBe('one');
    expect(one.querySelector('[data-frame-region=side]')).not.toBeNull();
    expect(host.querySelector('#omni')).not.toBeNull();
});

test('the pair forwards find to the list drawer and a caller cannot wipe the offset or fake the pair marker', () => {
    menuPageState.surface = true;
    const host = show({ pairOpen: true, pairTitle: 'appearance', find: snip('<input id="finder">'), style: 'color: red', 'data-pair': 'fake' });
    const [list, page] = roots(host) as [HTMLElement, HTMLElement];
    expect(list.querySelector('.oc-titlebar__find #finder')).not.toBeNull();
    expect([list.dataset.pair, page.dataset.pair]).toEqual(['list', 'page']);
    expect(page.getAttribute('style')).toContain('--oc-drawer-offset');
});
