/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MENU_PAGES } from './menu-pages';
import { initMenuPageShell, resetMenuPageShell, type ShellDeps } from './menu-page-shell.svelte';

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

function press(target: Element): boolean {
    const event = new Event('pointerdown', { bubbles: true, cancelable: true });
    target.dispatchEvent(event);
    return event.defaultPrevented;
}

function el(tag: string, attrs: Record<string, string> = {}, parent: Element = document.body): HTMLElement {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    parent.append(node);
    return node;
}

function closedCount(): number {
    return Object.values(closers).reduce((n, fn) => n + fn.mock.calls.length, 0);
}

beforeEach(() => {
    resetMenuPageShell();
    document.body.className = '';
    for (const page of MENU_PAGES) el('div', { id: page.containerId });
    el('div', { id: 'session-sidebar-flyout' });
    el('div', { id: 'session-sidebar-wrail' });
    closers = {};
    const ns: Record<string, unknown> = {};
    for (const page of MENU_PAGES) {
        closers[page.id] = vi.fn(() => document.getElementById(page.containerId)!.replaceChildren());
        ns[page.closer] = closers[page.id];
    }
    const deps: ShellDeps = { selectTab: vi.fn(), web: () => ns, surface: { start: () => true, stop: () => {}, refresh: () => true } };
    stop = initMenuPageShell(document, deps);
});

afterEach(() => {
    stop();
    document.body.replaceChildren();
    document.body.className = '';
    delete document.body.dataset.menuPage;
});

test('a press outside the open page closes it and is not prevented', async () => {
    const root = openPage('ledger-screen');
    await settle();
    const terminal = el('div', { class: 'xterm' });
    expect(press(terminal)).toBe(false);
    await vi.waitFor(() => expect(closers.ledger!).toHaveBeenCalledTimes(1));
    expect(root.isConnected).toBe(false);
});

test('a press inside the page, a portaled menu or modal, the hover menu or the rail leaves it open', async () => {
    const root = openPage('ledger-screen');
    await settle();
    const inner = el('button', {}, root);
    const menu = el('div', { role: 'menu' });
    const modal = el('div', { class: 'modal-overlay' });
    const flyout = el('button', {}, document.getElementById('session-sidebar-flyout')!);
    const rail = el('button', {}, document.getElementById('session-sidebar-wrail')!);
    for (const t of [inner, el('span', {}, menu), modal, flyout, rail]) press(t);
    await settle();
    expect(closedCount()).toBe(0);
});

test('with no page open a press closes nothing', async () => {
    press(el('div', { class: 'xterm' }));
    await settle();
    expect(closedCount()).toBe(0);
});

test('a press on the agents drawer list (a listbox) closes the page, a press in a page listbox does not', async () => {
    const root = openPage('ledger-screen');
    await settle();
    el('div', { role: 'listbox', id: 'x-page-list' }, root);
    press(root.querySelector('#x-page-list')!);
    await settle();
    expect(closedCount()).toBe(0);
    const list = el('div', { role: 'listbox', id: 'session-sidebar-list' });
    press(el('div', {}, list));
    await vi.waitFor(() => expect(closers.ledger!).toHaveBeenCalledTimes(1));
});

test('one press takes a settings stack down through its closer, not a history step back', async () => {
    openPage('settings-screen');
    await settle();
    const back = vi.spyOn(history, 'back');
    press(el('div', { class: 'xterm' }));
    await vi.waitFor(() => expect(closers.settings!).toHaveBeenCalledTimes(1));
    expect(back).not.toHaveBeenCalled();
});
