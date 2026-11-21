/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { MENU_PAGES } from './menu-pages';
import {
    closeMenuPageFromX, closeMenuPageGuarded, closeMenuPagesExcept, initMenuPageShell, openMenuPages, resetMenuPageShell, type ShellDeps,
} from './menu-page-shell.svelte';
import type { HashEnv } from './menu-page-hash';

let stop: () => void = () => {};
let deps: ShellDeps;
let stack: { hash: string; state: unknown }[];
let at: number;

function fakeEnv(): HashEnv {
    const env = {
        location: { pathname: '/', search: '', get hash() { return stack[at]!.hash; } },
        history: {
            get state() { return stack[at]!.state; },
            pushState(state: unknown, _t: string, url: string) { stack.splice(at + 1); stack.push({ hash: url.replace(/^\//, ''), state }); at = stack.length - 1; },
            replaceState(state: unknown, _t: string, url: string) { stack[at] = { hash: url.replace(/^\//, ''), state }; },
            back() { at = Math.max(0, at - 1); },
            go(n: number) { at = Math.max(0, Math.min(stack.length - 1, at + n)); },
        },
    };
    return env as unknown as HashEnv;
}

/** Open a page the way an opener does. */
function open(id: string): void {
    const page = MENU_PAGES.find((p) => p.id === id)!;
    closeMenuPagesExcept(id, document, deps);
    const root = document.createElement('div');
    root.append(document.createElement('h1'));
    document.getElementById(page.containerId)!.append(root);
}

const settle = async (): Promise<void> => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

beforeEach(() => {
    resetMenuPageShell();
    stack = [{ hash: '', state: null }];
    at = 0;
    const ns: Record<string, unknown> = {};
    for (const page of MENU_PAGES) {
        const div = document.createElement('div');
        div.id = page.containerId;
        document.body.append(div);
        ns[page.closer] = () => document.getElementById(page.containerId)!.replaceChildren();
        ns[page.closer.replace(/^close/, 'open')] = () => open(page.id);
    }
    deps = {
        selectTab: () => {},
        web: () => ns,
        hashEnv: fakeEnv(),
        origin: { drawerTab: () => null, generation: () => 0 },
        surface: { start: () => true, stop: () => {}, refresh: () => true },
        confirm: async () => true,
    };
    stop = initMenuPageShell(document, deps);
});

afterEach(() => {
    stop();
    document.body.replaceChildren();
});

test('the X after four pages closes all of them, clears the hash and leaves no entry for Back to reopen', async () => {
    for (const id of ['sessions', 'automations', 'warez', 'widgets']) { open(id); await settle(); }
    expect(openMenuPages(document).map((p) => p.id)).toEqual(['widgets']);
    expect(await closeMenuPageFromX(document, deps)).toBe(true);
    await settle();
    expect(openMenuPages(document)).toEqual([]);
    expect(stack[at]!.hash).toBe('');
    expect(at).toBe(0);
});

test('Escape on desktop is the X: it closes every stacked page and reopens none', async () => {
    for (const id of ['sessions', 'automations', 'warez', 'widgets']) { open(id); await settle(); }
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle(); await settle();
    expect(openMenuPages(document)).toEqual([]);
    expect(at).toBe(0);
});

test('Escape on a parked settings section brings settings back', async () => {
    open('settings'); await settle();
    open('hosts'); await settle();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle(); await settle();
    expect(openMenuPages(document).map((p) => p.id)).toEqual(['settings']);
});

test('the phone back arrow still retraces to the page under (unchanged)', async () => {
    for (const id of ['sessions', 'warez']) { open(id); await settle(); }
    await closeMenuPageGuarded(document, deps);
    await settle();
    expect(openMenuPages(document).map((p) => p.id)).toEqual(['sessions']);
});

test('a settings section X brings settings back', async () => {
    open('settings'); await settle();
    open('hosts'); await settle();
    expect(document.getElementById('settings-screen')!.hasAttribute('data-menu-parked')).toBe(true);
    await closeMenuPageFromX(document, deps);
    await settle();
    expect(openMenuPages(document).map((p) => p.id)).toEqual(['settings']);
    expect(document.getElementById('settings-screen')!.hasAttribute('data-menu-parked')).toBe(false);
});
