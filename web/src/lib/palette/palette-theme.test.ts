/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { PaletteItem } from './palette-sources';

const run = vi.fn();
const mk = (id: string, title: string, offline = false): PaletteItem => ({ id, kind: 'setting', title, subtitle: 'sub', offline, run });
const items = [mk('a', 'alpha one'), mk('b', 'alpha two'), mk('c', 'alpha remote', true)];

vi.mock('./palette-sources', () => ({
    buildCorpus: () => ({ items, actions: [], sessions: [], known: { host: [], project: [], state: [] } }),
    drawerRows: () => [],
    emptyGroups: () => [{ key: 'palette.group.results', items }],
}));

import Palette from './Palette.svelte';

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
    run.mockClear();
});

function open(initial = 'alpha'): HTMLInputElement {
    handle = mount(Palette, { target: document.body, props: { initial, onClose: () => {} } }) as Record<string, unknown>;
    flushSync();
    return document.querySelector<HTMLInputElement>('.oc-search input[data-field]')!;
}

const rowsOf = () => [...document.querySelectorAll<HTMLElement>('[role="option"]')];

describe('palette rendered on the shared layers', () => {
    it('focus is in the base search field', () => {
        const input = open();
        expect(input).toBeTruthy();
        expect(document.activeElement).toBe(input);
    });
    it('a click on a muted (offline) row opens it, and the row is not disabled', () => {
        open();
        const offline = rowsOf().find((r) => r.textContent?.includes('alpha remote'))!;
        expect(offline.getAttribute('aria-disabled')).toBeNull();
        expect(offline.hasAttribute('data-interactive')).toBe(true);
        offline.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
        flushSync();
        expect(run).toHaveBeenCalledTimes(1);
    });
    it('the clear x resets the active row to the first', () => {
        open();
        rowsOf()[1]!.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
        flushSync();
        expect(rowsOf()[1]!.hasAttribute('data-selected')).toBe(true);
        document.querySelector<HTMLButtonElement>('.oc-search__clear')!.click();
        flushSync();
        expect(rowsOf()[0]!.hasAttribute('data-selected')).toBe(true);
    });
});
