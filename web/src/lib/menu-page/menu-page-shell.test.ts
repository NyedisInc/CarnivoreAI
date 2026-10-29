/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const WEB = process.cwd();

import { MENU_PAGES, MENU_PAGE_OPEN_CLASS } from './menu-pages';
import { initMenuPageShell, menuPageState, pickDrawerTab, resetMenuPageShell, type ShellDeps } from './menu-page-shell.svelte';
import DrawerMenu from '../drawer-tabs/DrawerMenu.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

let stop: () => void = () => {};
let deps: ShellDeps;
let closers: Record<string, ReturnType<typeof vi.fn>>;

async function settle(): Promise<void> {
    await Promise.resolve();
    await Promise.resolve();
    flushSync();
}

function openPage(containerId: string): HTMLElement {
    const root = document.createElement('div');
    root.className = 'mgr';
    const title = document.createElement('h1');
    title.tabIndex = -1;
    root.append(title);
    document.getElementById(containerId)!.append(root);
    return root;
}

beforeEach(() => {
    resetMenuPageShell();
    document.body.className = '';
    for (const page of MENU_PAGES) {
        const div = document.createElement('div');
        div.id = page.containerId;
        document.body.append(div);
    }
    closers = {};
    const ns: Record<string, unknown> = {};
    for (const page of MENU_PAGES) {
        closers[page.id] = vi.fn(() => {
            document.getElementById(page.containerId)!.replaceChildren();
        });
        ns[page.closer] = closers[page.id];
    }
    deps = { selectTab: vi.fn(), web: () => ns };
    stop = initMenuPageShell(document, deps);
});

afterEach(() => {
    stop();
    document.body.replaceChildren();
    document.body.className = '';
    delete document.body.dataset.menuPage;
});

test('a page up puts the cover class on the body, and taking it down removes it', async () => {
    expect(document.body.classList.contains(MENU_PAGE_OPEN_CLASS)).toBe(false);
    openPage('settings-screen');
    await settle();
    expect(document.body.classList.contains(MENU_PAGE_OPEN_CLASS)).toBe(true);
    expect(document.body.dataset.menuPage).toBe('settings');
    expect(menuPageState.open).toBe('settings');
    document.getElementById('settings-screen')!.replaceChildren();
    await settle();
    expect(document.body.classList.contains(MENU_PAGE_OPEN_CLASS)).toBe(false);
    expect(document.body.dataset.menuPage).toBeUndefined();
    expect(menuPageState.open).toBeNull();
});

test('every menu page, opened any way, switches the drawer to its menu tab, except one flagged keepDrawerTab', async () => {
    for (const page of MENU_PAGES) {
        (deps.selectTab as ReturnType<typeof vi.fn>).mockClear();
        openPage(page.containerId);
        await settle();
        if (page.keepDrawerTab) expect(deps.selectTab, page.id).not.toHaveBeenCalled();
        else expect(deps.selectTab, page.id).toHaveBeenCalledWith('menu');
        expect(menuPageState.open).toBe(page.id);
        document.getElementById(page.containerId)!.replaceChildren();
        await settle();
    }
});

test('a click on the Agents tab no longer restores the last view; Escape from Home keeps that job (#1542, #2359)', async () => {
    const restore = vi.fn();
    const withRestore = { ...deps, restoreLastView: restore } as unknown as ShellDeps;
    openPage('settings-screen');
    await settle();
    (pickDrawerTab as (...a: unknown[]) => void)('agents', document, withRestore, true);
    expect(restore).not.toHaveBeenCalled();
    expect(closers.settings).toHaveBeenCalledTimes(1);
});

test('picking the Agents tab takes the open page down; any other tab leaves it up', async () => {
    openPage('settings-screen');
    await settle();
    pickDrawerTab('menu', document, deps);
    expect(closers['settings']).not.toHaveBeenCalled();
    pickDrawerTab('agents', document, deps);
    expect(closers['settings']).toHaveBeenCalledTimes(1);
    expect(deps.selectTab).toHaveBeenLastCalledWith('agents');
    await settle();
    expect(menuPageState.open).toBeNull();
});

test('a second page coming up closes the first, and focus stays in the new page', async () => {
    openPage('themes-screen');
    await settle();
    const root = openPage('settings-screen');
    const title = root.querySelector('h1')!;
    title.focus();
    await settle();
    expect(closers.themes).toHaveBeenCalledTimes(1);
    expect(closers.settings).not.toHaveBeenCalled();
    expect(document.getElementById('themes-screen')!.children).toHaveLength(0);
    expect(menuPageState.open).toBe('settings');
    expect(document.activeElement).toBe(title);
});

test('the drawer menu marks the open page\'s row, and only that row', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    const menu = mount(DrawerMenu, { target });
    flushSync();
    const marked = () =>
        [...target.querySelectorAll('[data-rail-item][aria-current="page"]')].map((b) => b.getAttribute('data-rail-item'));
    expect(marked()).toEqual([]);
    openPage('settings-screen');
    await settle();
    expect(marked()).toEqual(['settings']);
    expect(target.querySelector('[data-rail-item="settings"]')!.classList.contains('oc-nav-item--active')).toBe(true);
    document.getElementById('settings-screen')!.replaceChildren();
    openPage('sessions-screen');
    await settle();
    expect(marked()).toEqual(['sessions']);
    await unmount(menu);
});

test('the cover stylesheet names exactly the containers the shell watches', () => {
    const css = readFileSync(path.join(WEB, 'src/lib/menu-page/menu-page.css'), 'utf8');
    const lists = [...css.matchAll(/:is\(([^)]*)\)/g)].map((m) =>
        (m[1] ?? '').split(',').map((s) => s.trim().replace(/^#/, '')).sort(),
    );
    const expected = MENU_PAGES.map((p) => p.containerId).sort();
    expect(lists.length).toBeGreaterThanOrEqual(2);
    for (const list of lists) expect(list).toEqual(expected);
});

test('the index page carries every container the shell watches, plus the bar', () => {
    const html = readFileSync(path.join(WEB, '../client/index.html'), 'utf8');
    for (const id of [...MENU_PAGES.map((p) => p.containerId), 'menu-page-bar']) {
        expect(html, id).toContain(`<div id="${id}"></div>`);
    }
});
