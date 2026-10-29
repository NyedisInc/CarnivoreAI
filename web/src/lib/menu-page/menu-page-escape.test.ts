/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MENU_PAGES } from './menu-pages';
import { initMenuPageShell, resetMenuPageShell, type ShellDeps } from './menu-page-shell.svelte';
import { ownsEscape } from '../sidebar-widgets/escape-guards';

let stop: () => void = () => {};
let closers: Record<string, ReturnType<typeof vi.fn>>;

async function settle(): Promise<void> {
    await Promise.resolve();
    await Promise.resolve();
}

function openPage(containerId: string): HTMLElement {
    const root = document.createElement('div');
    document.getElementById(containerId)!.append(root);
    return root;
}

function escapeOn(target: EventTarget): boolean {
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    target.dispatchEvent(event);
    return event.defaultPrevented;
}

function closedCount(): number {
    return Object.values(closers).reduce((n, fn) => n + fn.mock.calls.length, 0);
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
        closers[page.id] = vi.fn(() => document.getElementById(page.containerId)!.replaceChildren());
        ns[page.closer] = closers[page.id];
    }
    const deps: ShellDeps = { selectTab: vi.fn(), web: () => ns };
    stop = initMenuPageShell(document, deps);
});

afterEach(() => {
    stop();
    document.body.replaceChildren();
    document.body.className = '';
    delete document.body.dataset.menuPage;
});

test('Escape closes every menu page, through that page\'s own closer', async () => {
    for (const page of MENU_PAGES) {
        openPage(page.containerId);
        await settle();
        expect(escapeOn(document.body), page.id).toBe(true);
        await vi.waitFor(() => expect(closers[page.id]!, page.id).toHaveBeenCalledTimes(1));
        expect(document.getElementById(page.containerId)!.firstElementChild, page.id).toBeNull();
        expect(location.hash, page.id).toBe('');
        await settle();
    }
});

test('with no menu page open Escape is never claimed, so the terminal keeps it', () => {
    const term = document.createElement('div');
    term.className = 'xterm';
    document.body.append(term);
    expect(escapeOn(term)).toBe(false);
    expect(closedCount()).toBe(0);
});

test('Escape that something closer already handled is not taken again', async () => {
    const root = openPage('sessions-screen');
    await settle();
    root.addEventListener('keydown', (e) => e.preventDefault());
    escapeOn(root);
    expect(closedCount()).toBe(0);
    (closers.sessions! as unknown as () => void)();
    await settle();
});

test('a text field holding text keeps its Escape; an empty one lets the page close', async () => {
    const root = openPage('settings-screen');
    const input = document.createElement('input');
    input.type = 'text';
    input.value = 'wrap';
    root.append(input);
    await settle();
    expect(escapeOn(input)).toBe(false);
    expect(closedCount()).toBe(0);
    input.value = '';
    expect(escapeOn(input)).toBe(true);
    await vi.waitFor(() => expect(closers.settings!).toHaveBeenCalledTimes(1));
});

test('a textarea, a select and an editable region always keep Escape', () => {
    const area = document.createElement('textarea');
    const select = document.createElement('select');
    const editable = document.createElement('div');
    editable.contentEditable = 'true';
    Object.defineProperty(editable, 'isContentEditable', { value: true });
    expect([area, select, editable].map(ownsEscape)).toEqual([true, true, true]);
    expect(ownsEscape(document.createElement('button'))).toBe(false);
    expect(ownsEscape(null)).toBe(false);
});

test('a dialog or an open menu on top of the page keeps Escape', async () => {
    openPage('ledger-screen');
    await settle();
    const dialog = document.createElement('div');
    dialog.className = 'modal-overlay';
    document.body.append(dialog);
    expect(escapeOn(document.body)).toBe(false);
    dialog.remove();
    const menu = document.createElement('div');
    menu.setAttribute('role', 'menu');
    document.body.append(menu);
    expect(escapeOn(document.body)).toBe(false);
    expect(closedCount()).toBe(0);
    menu.remove();
    expect(escapeOn(document.body)).toBe(true);
    await vi.waitFor(() => expect(closers.ledger!).toHaveBeenCalledTimes(1));
    await settle();
});

test('a closed dialog or menu left in the document does not hold Escape', async () => {
    openPage('plugins-screen');
    await settle();
    const closedModal = document.createElement('div');
    closedModal.className = 'modal-overlay';
    closedModal.hidden = true;
    const closedMenu = document.createElement('div');
    closedMenu.setAttribute('role', 'menu');
    closedMenu.hidden = true;
    document.body.append(closedModal, closedMenu);
    expect(escapeOn(document.body)).toBe(true);
    await vi.waitFor(() => expect(closers.plugins!).toHaveBeenCalledTimes(1));
});

test('stopping the shell removes the listener', async () => {
    openPage('docs-screen');
    await settle();
    stop();
    expect(escapeOn(document.body)).toBe(false);
    expect(closedCount()).toBe(0);
    stop = initMenuPageShell(document, { selectTab: vi.fn(), web: () => null });
});
