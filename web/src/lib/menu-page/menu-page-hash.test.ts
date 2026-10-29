/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { MENU_PAGES, menuPage } from './menu-pages';
import { clearPageHash, hashNamesPage, pageOfHash, pushPageHash, type HashEnv } from './menu-page-hash';
import { initMenuPageShell, reconcilePageWithHash, resetMenuPageShell, type ShellDeps } from './menu-page-shell.svelte';

let stop: () => void = () => {};
let deps: ShellDeps;
let opened: string[];

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
}

function openPage(id: string): void {
    const page = menuPage(id)!;
    document.getElementById(page.containerId)!.append(document.createElement('div'));
}

function closePage(id: string): void {
    document.getElementById(menuPage(id)!.containerId)!.replaceChildren();
}

beforeEach(() => {
    resetMenuPageShell();
    window.history.replaceState(null, '', '/');
    opened = [];
    const ns: Record<string, unknown> = {};
    for (const page of MENU_PAGES) {
        const div = document.createElement('div');
        div.id = page.containerId;
        document.body.append(div);
        ns[page.closer] = vi.fn(() => closePage(page.id));
        ns[page.closer.replace(/^close/, 'open')] = vi.fn(() => {
            opened.push(page.id);
            openPage(page.id);
        });
    }
    deps = { selectTab: vi.fn(), web: () => ns };
    stop = initMenuPageShell(document, deps);
});

afterEach(() => {
    stop();
    document.body.replaceChildren();
    window.history.replaceState(null, '', '/');
});

test('a fragment names its page, bare or one level down, and an unrelated one names none', () => {
    expect(pageOfHash('#settings')?.id).toBe('settings');
    expect(pageOfHash('#settings/hosts?highlight=x')?.id).toBe('settings');
    expect(pageOfHash('#wrappers')?.id).toBe('settings');
    expect(pageOfHash('#shortcuts')?.id).toBe('settings');
    expect(pageOfHash('#pack')?.id).toBe('hosts');
    expect(pageOfHash('#hosts/ssh')?.id).toBe('hosts');
    expect(pageOfHash('#docs/wrappers')?.id).toBe('docs');
    expect(pageOfHash('#settingsfoo')).toBeNull();
    expect(pageOfHash('')).toBeNull();
    expect(hashNamesPage('#plugins', menuPage('themes')!)).toBe(false);
});

test('every menu page has a hash and no two pages claim the same one', () => {
    const all = MENU_PAGES.flatMap((p) => p.hashes);
    expect(MENU_PAGES.every((p) => p.hashes.length > 0)).toBe(true);
    expect(new Set(all).size).toBe(all.length);
});

test('opening a page pushes its hash, one history entry, and back-state is kept', async () => {
    const before = window.history.length;
    openPage('plugins');
    await settle();
    expect(window.location.hash).toBe('#plugins');
    expect(window.history.length).toBe(before + 1);
});

test('a page that already carries a deeper fragment of its own is not pushed over', async () => {
    window.history.replaceState(null, '', '#settings/appearance');
    const before = window.history.length;
    openPage('settings');
    await settle();
    expect(window.location.hash).toBe('#settings/appearance');
    expect(window.history.length).toBe(before);
});

test('a page leaving with nothing in its place drops its hash', async () => {
    openPage('themes');
    await settle();
    expect(window.location.hash).toBe('#themes');
    closePage('themes');
    await settle();
    expect(window.location.hash).toBe('');
});

test('a page replacing another keeps the new page\'s link', async () => {
    openPage('themes');
    await settle();
    closePage('themes');
    openPage('plugins');
    await settle();
    expect(window.location.hash).toBe('#plugins');
});

test('a hash that names no page takes an open page down (back to the normal view)', async () => {
    openPage('plugins');
    await settle();
    window.history.replaceState(null, '', '/');
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    await settle();
    expect(document.getElementById('plugins-screen')!.firstElementChild).toBeNull();
});

test('a hash that names a page that is not up puts it up, once', () => {
    window.history.replaceState(null, '', '#ledger');
    reconcilePageWithHash(document, deps, '#ledger');
    reconcilePageWithHash(document, deps, '#ledger');
    expect(opened).toEqual(['ledger']);
});

test('push and clear do nothing without a window pair, and clear leaves another page\'s hash alone', () => {
    expect(pushPageHash(menuPage('themes')!, null)).toBe(false);
    expect(clearPageHash(menuPage('themes')!, null)).toBe(false);
    const env = { location: { hash: '#plugins', pathname: '/', search: '' }, history: { pushState: vi.fn(), replaceState: vi.fn(), state: null } } as unknown as HashEnv;
    expect(clearPageHash(menuPage('themes')!, env)).toBe(false);
    expect(env.history.replaceState).not.toHaveBeenCalled();
});

test('the swarm settings fragments open the Plugins page (huddle\'s section), and a plugin deep link names it too', () => {
    expect(pageOfHash('#swarm-settings')?.id).toBe('plugins');
    expect(pageOfHash('#interactive-todo')?.id).toBe('plugins');
    expect(pageOfHash('#plugins/flow/settings')?.id).toBe('plugins');
    expect(pageOfHash('#swarm')?.id).toBe('huddle-swarm');
});
