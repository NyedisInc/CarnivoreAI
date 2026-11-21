/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { MENU_PAGES } from './menu-pages';
import {
    closeMenuPageFromX, closeMenuPagesExcept, initMenuPageShell, openMenuPages, resetMenuPageShell, type ShellDeps,
} from './menu-page-shell.svelte';

let stop: () => void = () => {};
let deps: ShellDeps;

/** Open a page the way an opener does. */
function open(id: string): void {
    const page = MENU_PAGES.find((p) => p.id === id)!;
    closeMenuPagesExcept(id, document, deps);
    const root = document.createElement('div');
    root.append(document.createElement('h1'));
    document.getElementById(page.containerId)!.append(root);
}

const settle = async (ms = 0): Promise<void> => { await new Promise((r) => setTimeout(r, ms)); };

beforeEach(() => {
    resetMenuPageShell();
    history.replaceState(null, '', '#sessions');
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

test('a deep-linked first page does not reopen when the X lands history back on its entry', async () => {
    open('sessions'); await settle();
    for (const id of ['automations', 'warez', 'widgets']) { open(id); await settle(); }
    expect(await closeMenuPageFromX(document, deps)).toBe(true);
    await settle(100);
    expect(openMenuPages(document)).toEqual([]);
    expect(location.hash).toBe('');
});
