/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import KeymapScreen from './KeymapScreen.svelte';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

const t = (key: string): string => (enCatalog as Record<string, string>)[key] ?? key;
if (typeof CSS === 'undefined') (globalThis as { CSS?: unknown }).CSS = {};
if (!CSS.escape) CSS.escape = (v: string): string => v.replace(/[^\w-]/g, (c) => `\\${c}`);
let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function show(query: string): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(KeymapScreen, { target, props: { query, t } });
    flushSync();
    return target;
}

const rowIds = (host: HTMLElement): string[] => [...host.querySelectorAll<HTMLElement>('[data-action]')].map((el) => el.dataset.action ?? '');
const branch = (host: HTMLElement, id: string): HTMLElement => host.querySelector<HTMLElement>(`[data-tree-item="${id}"]`)!;

test('with no search it shows the top groups, each with its count, and tells the reader shortcuts can be changed', () => {
    const host = show('');
    const tops = [...host.querySelectorAll<HTMLElement>('[data-tree-branch][aria-level="1"]')];
    expect(tops.length).toBeGreaterThanOrEqual(5);
    expect(tops.every((el) => Number(el.querySelector('.oc-tree__count')?.textContent) > 0)).toBe(true);
    expect(host.querySelector('[data-keymap-note]')?.textContent).toMatch(/change/);
    expect(show('back').querySelectorAll('[data-keymap-change]').length).toBeGreaterThan(0);
});

test('a branch opens on click and shuts on the arrow key, and Enter folds it too', () => {
    const host = show('');
    const first = host.querySelector<HTMLElement>('[data-tree-branch][aria-level="2"]')!;
    const id = first.dataset.treeItem!;
    expect(first.getAttribute('aria-expanded')).toBe('false');
    first.click();
    flushSync();
    expect(branch(host, id).getAttribute('aria-expanded')).toBe('true');
    branch(host, id).focus();
    branch(host, id).dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true }));
    flushSync();
    expect(branch(host, id).getAttribute('aria-expanded')).toBe('false');
    branch(host, id).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    flushSync();
    expect(branch(host, id).getAttribute('aria-expanded')).toBe('true');
});

test('find by name keeps the tree and opens only the branches that matched', () => {
    const host = show('zoom the terminal');
    expect(rowIds(host)).toContain('terminal.zoom.toggle');
    expect(rowIds(host).length).toBeLessThan(10);
    expect(host.querySelectorAll('[data-tree-branch]').length).toBeGreaterThan(0);
    expect(host.querySelector('[data-tree-item="menus"]')).toBeNull();
});

test('find by shortcut lists what the pressed chord is bound to, and Escape stops listening', () => {
    const host = show('');
    host.querySelector<HTMLButtonElement>('[data-keymap-press]')!.click();
    flushSync();
    expect(host.querySelector('[data-keymap-hint]')).not.toBeNull();
    host.querySelector<HTMLButtonElement>('[role="radio"]')!.click();
    flushSync();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', code: 'KeyK', metaKey: true, bubbles: true, cancelable: true }));
    flushSync();
    expect(rowIds(host)).toEqual(['palette.open']);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    flushSync();
    expect(host.querySelector('[data-keymap-hint]')).toBeNull();
    expect(host.querySelectorAll('[data-tree-branch][aria-level="1"]').length).toBeGreaterThanOrEqual(5);
});

test('a mouse row draws its gesture once, from the catalog, never as a keycap', () => {
    const host = show('close a tab');
    const row = host.querySelector<HTMLElement>('[data-action="mouse.tab.close"]')!;
    expect(row).not.toBeNull();
    expect(row.querySelectorAll('.oc-keycap')).toHaveLength(0);
    expect(row.textContent).toMatch(/middle click/);
});

test('only rows the app reads from the registry have a change key; every other row shows its default and none', () => {
    const wired = show('layout you were on');
    expect(wired.querySelector('[data-action="history.back"]')).not.toBeNull();
    expect(wired.querySelector('[data-keymap-change][data-action-for="history.back"]')).not.toBeNull();
    expect(wired.querySelector('[role="treeitem"] [data-keymap-change]')).toBeNull();
    const unwired = show('zoom the terminal');
    unwired.querySelector<HTMLButtonElement>('[role="radio"]')!.click();
    flushSync();
    expect(unwired.querySelector('[data-action="terminal.zoom.toggle"]')).not.toBeNull();
    expect(unwired.querySelector('[data-keymap-change][data-action-for="terminal.zoom.toggle"]')).toBeNull();
    expect(unwired.querySelector('[data-action="terminal.zoom.toggle"] .oc-keycaps')).not.toBeNull();
    expect(unwired.querySelector('[data-keymap-note]')?.textContent).not.toMatch(/later|moves over|migrat/);
});
