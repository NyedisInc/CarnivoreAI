/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { MENU_PAGES } from './menu-pages';
import { closeMenuPageGuarded, initMenuPageShell, resetMenuPageShell, type ShellDeps } from './menu-page-shell.svelte';
import { isPageDirty, mayClosePage, registerPageDirty, resetPageDirty, type ConfirmFn } from './menu-page-dirty';

let stop: () => void = () => {};
let closers: Record<string, ReturnType<typeof vi.fn>>;
let confirm: ReturnType<typeof vi.fn<ConfirmFn>>;
let answer: boolean;

async function settle(): Promise<void> {
    await Promise.resolve();
    await Promise.resolve();
}

function openPage(containerId: string): HTMLElement {
    const root = document.createElement('div');
    document.getElementById(containerId)!.append(root);
    return root;
}

function escape(): void {
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
}

beforeEach(() => {
    resetMenuPageShell();
    resetPageDirty();
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
    answer = false;
    confirm = vi.fn<ConfirmFn>(async () => answer);
    const deps: ShellDeps = { selectTab: vi.fn(), web: () => ns, confirm, surface: null };
    stop = initMenuPageShell(document, deps);
});

afterEach(() => {
    stop();
    resetPageDirty();
    document.body.replaceChildren();
    document.body.className = '';
    delete document.body.dataset.menuPage;
});

test('a dirty page asks before Escape closes it, and stays up on "keep editing"', async () => {
    registerPageDirty('settings', () => true);
    openPage('settings-screen');
    await settle();
    escape();
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    const [title, message, , confirmLabel, cancelLabel, variant] = confirm.mock.calls[0]!;
    expect([title, message, confirmLabel, cancelLabel, variant]).toEqual([
        'unsaved changes',
        'this page has changes that are not saved yet. close it and lose them?',
        'discard and close',
        'keep editing',
        'danger',
    ]);
    await settle();
    expect(closers.settings!).not.toHaveBeenCalled();
    expect(document.getElementById('settings-screen')!.firstElementChild).not.toBeNull();
});

test('confirming the discard closes the page and drops what the page said to drop', async () => {
    const discard = vi.fn();
    registerPageDirty('settings', () => true, discard);
    openPage('settings-screen');
    await settle();
    answer = true;
    escape();
    await vi.waitFor(() => expect(closers.settings!).toHaveBeenCalledTimes(1));
    expect(discard).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledTimes(1);
});

test('a page with nothing unsaved, or no check at all, closes without a question', async () => {
    registerPageDirty('settings', () => false);
    openPage('settings-screen');
    await settle();
    escape();
    await vi.waitFor(() => expect(closers.settings!).toHaveBeenCalledTimes(1));
    await settle();
    openPage('sessions-screen');
    await settle();
    escape();
    await vi.waitFor(() => expect(closers.sessions!).toHaveBeenCalledTimes(1));
    expect(confirm).not.toHaveBeenCalled();
});

test('only the open page\'s own check counts: another page\'s unsaved state never blocks it', async () => {
    registerPageDirty('settings', () => true);
    openPage('sessions-screen');
    await settle();
    escape();
    await vi.waitFor(() => expect(closers.sessions!).toHaveBeenCalledTimes(1));
    expect(confirm).not.toHaveBeenCalled();
});

test('a second Escape while the question is up does not stack a second question', async () => {
    registerPageDirty('settings', () => true);
    openPage('settings-screen');
    await settle();
    let release: (v: boolean) => void = () => {};
    confirm.mockImplementation(() => new Promise<boolean>((r) => { release = r; }));
    escape();
    escape();
    await settle();
    expect(confirm).toHaveBeenCalledTimes(1);
    release(false);
    await settle();
    expect(closers.settings!).not.toHaveBeenCalled();
});

test('the back arrow and the bar take the same guarded close', async () => {
    registerPageDirty('settings', () => true);
    openPage('settings-screen');
    await settle();
    expect(await closeMenuPageGuarded(document, { selectTab: vi.fn(), web: () => ({}), confirm })).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);
});

test('a dirty page with no confirm dialog on the page stays open, never a silent loss', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    registerPageDirty('settings', () => true);
    expect(await mayClosePage('settings', null)).toBe(false);
    expect(error).toHaveBeenCalled();
    error.mockRestore();
});

test('a check that throws counts as saved, so a broken page never traps the person', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    registerPageDirty('settings', () => { throw new Error('boom'); });
    expect(isPageDirty('settings')).toBe(false);
    error.mockRestore();
});

test('unregistering takes the check away', () => {
    const off = registerPageDirty('settings', () => true);
    expect(isPageDirty('settings')).toBe(true);
    off();
    expect(isPageDirty('settings')).toBe(false);
});
