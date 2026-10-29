/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import InfoScreen from './InfoScreen.svelte';
import { FUZZY_PREF_KEY } from '../help/fuzzy-pref';

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
    localStorage.clear();
    vi.restoreAllMocks();
});

function render(): HTMLElement {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 500 })));
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(InfoScreen, { target, props: { view: 'changelog', embedded: true } });
    flushSync();
    return target;
}

const box = (root: HTMLElement): HTMLElement => root.querySelector('[data-changelog-fuzzy]') as HTMLElement;

describe('the changelog fuzzy checkbox', () => {
    test('is drawn off by default, labelled fuzzy', () => {
        const root = render();
        expect(box(root)).not.toBeNull();
        expect(box(root).getAttribute('aria-checked')).toBe('false');
        expect(box(root).textContent).toContain('fuzzy');
    });

    test('a click turns it on and remembers it on this device', () => {
        const root = render();
        box(root).click();
        flushSync();
        expect(box(root).getAttribute('aria-checked')).toBe('true');
        expect(localStorage.getItem(FUZZY_PREF_KEY)).toBe('1');
    });

    test('a remembered on comes back on', () => {
        localStorage.setItem(FUZZY_PREF_KEY, '1');
        expect(box(render()).getAttribute('aria-checked')).toBe('true');
    });
});
