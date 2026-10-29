/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { activateRow, onRowActionClick, onRowClick, paintSelection } from './clicks';
import { claim as chromeClaim } from './chrome-clicks';
import { onListClick } from './rename';
import { activate as activateBrowserRow, onKeyClick as onBrowserKeyClick } from './browser-rows';
import { runRestart as runRestartFlow } from './restart-click';

vi.mock('./chrome-clicks', () => ({ claim: vi.fn(() => false), onGroupToggleClick: vi.fn() }));
vi.mock('./rename', () => ({ onListClick: vi.fn(() => false), afterRender: vi.fn() }));
vi.mock('./browser-rows', () => ({ onKeyClick: vi.fn(async () => {}), activate: vi.fn(() => false) }));
vi.mock('./restart-click', () => ({ runRestart: vi.fn(async () => {}) }));

const shell = vi.hoisted(() => ({ claimed: false, log: (_label: string) => {} }));
vi.mock('../sidebar-shell/row-drag', () => ({
    tookClick: () => { shell.log('tookClick'); return shell.claimed; },
}));
vi.mock('../sidebar-shell/row-reorder', () => ({
    onPinClick: (_e: MouseEvent, btn: Element) => { shell.log(`pin:${btn.getAttribute('data-pin-session')}`); },
}));

type Win = Record<string, unknown>;
const win = window as unknown as Win;
const NAMES = ['CloudeWeb', 'SessionSidebarLayouts',
    'SessionRowActions', 'NavigationGeneration', 'SoloWindow', 'App', 'CloudeTerminal',
    'TerminalController', 'API'];

let calls: unknown[][] = [];
let ctrl: Record<string, any>;
let list: HTMLElement;

function rec(label: string, result?: unknown): (...a: unknown[]) => unknown {
    return (...a) => { calls.push([label, ...a]); return result; };
}

function quietPage(): void {
    vi.mocked(chromeClaim).mockImplementation(rec('chrome', false) as never);
    shell.claimed = false;
    shell.log = (label) => { calls.push([label]); };
    vi.mocked(onListClick).mockImplementation(rec('rename', false) as never);
    win.SessionRowActions = {
        ATTR_ACTION: 'data-session-action', ATTR_NAME: 'data-session-name', ACTION_CLOSE: 'close', ACTION_RESTART: 'restart',
        confirm: vi.fn(async () => true),
    };
    win.API = {
        getSession: vi.fn(async () => ({ id: 'info' })), adoptSession: vi.fn(async () => ({ session: { id: 'adopted' } })),
        destroySession: vi.fn(async () => ({})), destroyExternalSession: vi.fn(async () => ({})),
    };
    win.App = { returnToExistingTerminal: vi.fn(async () => {}) };
    win.CloudeTerminal = { SCROLLBACK_ROWS: 500 };
}

function addRow(name: string, attrs: Record<string, string> = {}): HTMLElement {
    const row = document.createElement('div');
    row.className = 'session-sidebar-row';
    row.dataset.name = name;
    for (const [k, v] of Object.entries(attrs)) row.setAttribute(k, v);
    list.append(row);
    return row;
}

async function click(el: Element): Promise<MouseEvent> {
    const e = new MouseEvent('click', { bubbles: true });
    Object.defineProperty(e, 'target', { value: el });
    await onRowClick(ctrl as never, e);
    return e;
}

beforeEach(() => {
    const g = globalThis as { CSS?: { escape?(v: string): string } };
    if (!g.CSS || typeof g.CSS.escape !== 'function') g.CSS = { ...(g.CSS || {}), escape: (v: string) => String(v).replace(/["\\\]\[]/g, '\\$&') };
    calls = [];
    document.body.innerHTML = '<div id="list"></div>';
    list = document.getElementById('list')!;
    ctrl = {
        listEl: list, _activeTmuxName: null, _pendingSelection: null, _lastSig: 'sig',
        _closeAfterSwitch: vi.fn(), repaint: vi.fn(), _fetchAndRender: vi.fn(async () => {}),
    };
    quietPage();
});

afterEach(() => { for (const n of NAMES) delete win[n]; });

describe('what claims a click before the row switch', () => {
    test('the list chrome claims first; nothing else is asked', async () => {
        vi.mocked(chromeClaim).mockImplementation(rec('chrome', true) as never);
        await click(addRow('cloude_a'));
        expect(calls.map((c) => c[0])).toEqual(['chrome']);
        expect(ctrl._closeAfterSwitch).not.toHaveBeenCalled();
    });

    test('a row the shell drew is left to the shell', async () => {
        win.CloudeWeb = { sidebarShell: { owns: () => true, paintSelection: vi.fn() } };
        await click(addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect((win.API as any).getSession).not.toHaveBeenCalled();
    });

    test('a click that ended a drag is consumed before the pin, rename and row are asked', async () => {
        shell.claimed = true;
        await click(addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect(calls.map((c) => c[0])).toEqual(['chrome', 'tookClick']);
    });

    test('a rename in progress, then a pin, each swallow the click', async () => {
        vi.mocked(onListClick).mockImplementation(rec('rename', true) as never);
        await click(addRow('cloude_a'));
        expect(calls.map((c) => c[0])).toEqual(['chrome', 'tookClick', 'rename']);
        calls = [];
        vi.mocked(onListClick).mockImplementation(rec('rename', false) as never);
        const pinRow = addRow('cloude_b');
        const pin = document.createElement('button');
        pin.setAttribute('data-pin-session', 'cloude_b');
        pinRow.append(pin);
        await click(pin);
        expect(calls.map((c) => c[0])).toEqual(['chrome', 'tookClick', 'rename', 'pin:cloude_b']);
    });

    test('the keep-awake cup flips the flag through the store, repaints, and never switches conversation', async () => {
        const setKeepAwake = vi.fn(async () => {});
        win.CloudeWeb = { autoSleep: { isKeptAwake: () => false, setKeepAwake } };
        const row = addRow('cloude_a', { 'data-session-id': 'ses_a' });
        const btn = document.createElement('button');
        btn.setAttribute('data-keep-awake-session', 'cloude_a');
        row.append(btn);
        const e = await click(btn);
        await Promise.resolve();
        expect(setKeepAwake).toHaveBeenCalledWith('cloude_a', true);
        expect(ctrl.repaint).toHaveBeenCalled();
        expect(e.cancelBubble).toBe(true);
        expect((win.API as any).getSession).not.toHaveBeenCalled();
    });

    test.each([
        ['data-subagents-session-id', 'openSubagentList'],
        ['data-timers-session-id', 'openTimerList'],
    ])('the %s chip opens its compiled list with the session id and never switches conversation', async (attr, opener) => {
        const open = vi.fn();
        win.CloudeWeb = { [opener]: open };
        const row = addRow('cloude_a', { 'data-session-id': 'ses_a' });
        const btn = document.createElement('button');
        btn.setAttribute(attr, 'ses_9');
        row.append(btn);
        const e = await click(btn);
        expect(open).toHaveBeenCalledTimes(1);
        expect(open.mock.calls[0]?.[1]).toBe('ses_9');
        expect(e.cancelBubble).toBe(true);
        expect((win.API as any).getSession).not.toHaveBeenCalled();
    });

    test('the share mark is claimed even when the row menu bridge is missing, so it never switches conversation', async () => {
        const err = vi.spyOn(console, 'error').mockImplementation(() => {});
        const row = addRow('cloude_a', { 'data-session-id': 'ses_a' });
        const btn = document.createElement('button');
        btn.setAttribute('data-share-session-id', 'x');
        row.append(btn);
        await click(btn);
        expect(err).toHaveBeenCalled();
        expect((win.API as any).getSession).not.toHaveBeenCalled();
        err.mockRestore();
    });

    test('the share mark opens the share plugin for its session, through the one runCplug path', async () => {
        const runCplug = vi.fn(async () => {});
        win.CloudeWeb = { rowMenu: { runCplug } };
        const btn = document.createElement('button');
        btn.setAttribute('data-share-session-id', 'ses_x');
        btn.setAttribute('data-share-session', 'cloude_a');
        addRow('cloude_a').append(btn);
        await click(btn);
        expect(runCplug).toHaveBeenCalledWith('share', { name: 'cloude_a', sessionId: 'ses_x' });
    });

    test('a browser row key press goes to the browsers module', async () => {
        vi.mocked(onBrowserKeyClick).mockImplementation(rec('browserKey') as never);
        const btn = document.createElement('button');
        btn.setAttribute('data-browser-row-action', 'close');
        addRow('browser:1').append(btn);
        await click(btn);
        expect(calls.some((c) => c[0] === 'browserKey')).toBe(true);
    });

    test('a row action button runs the destructive action, not the switch', async () => {
        const row = addRow('cloude_a', { 'data-session-id': 'ses_a' });
        const btn = document.createElement('button');
        btn.setAttribute('data-session-action', 'close');
        btn.setAttribute('data-session-name', 'cloude_a');
        row.append(btn);
        await click(btn);
        expect((win.API as any).destroySession).toHaveBeenCalledWith('ses_a');
        expect((win.API as any).getSession).not.toHaveBeenCalled();
    });

    test('a click on the row body switches to it', async () => {
        await click(addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect((win.API as any).getSession).toHaveBeenCalledWith('ses_a', expect.objectContaining({ scrollbackLines: 500 }));
        expect((win.App as any).returnToExistingTerminal).toHaveBeenCalledWith({ id: 'info' });
        expect(ctrl._closeAfterSwitch).toHaveBeenCalledTimes(1);
    });

    test('a click outside any row does nothing', async () => {
        await click(list);
        expect((win.API as any).getSession).not.toHaveBeenCalled();
    });
});

describe('activateRow', () => {
    test('an asleep row, a browser row and a Layout row never reach the network', async () => {
        await activateRow(ctrl as never, addRow('cloude_z', { 'data-asleep': '1', 'data-session-id': 'ses_z' }));
        vi.mocked(activateBrowserRow).mockImplementationOnce(rec('browser.activate', true) as never);
        await activateRow(ctrl as never, addRow('browser:1'));
        win.SessionSidebarLayouts = { activate: rec('layout.activate', true) };
        await activateRow(ctrl as never, addRow('layout:u'));
        expect((win.API as any).getSession).not.toHaveBeenCalled();
        expect((win.API as any).adoptSession).not.toHaveBeenCalled();
    });

    test('the row already attached only closes the drawer; on Home it switches', async () => {
        ctrl._activeTmuxName = 'cloude_a';
        await activateRow(ctrl as never, addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect(ctrl._closeAfterSwitch).toHaveBeenCalledTimes(1);
        expect((win.API as any).getSession).not.toHaveBeenCalled();
        win.App = { currentScreen: 'launchpad', returnToExistingTerminal: vi.fn(async () => {}) };
        await activateRow(ctrl as never, addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect((win.API as any).getSession).toHaveBeenCalledTimes(1);
    });

    test('a second click on the row being switched to is ignored while its navigation is current', async () => {
        win.NavigationGeneration = { begin: () => 7, isCurrent: () => true, keep: () => true };
        ctrl._pendingSelection = { name: 'cloude_a', nav: 7 };
        await activateRow(ctrl as never, addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect((win.API as any).getSession).not.toHaveBeenCalled();
    });

    test('a popped-out session is focused in its own window and not bound here', async () => {
        win.SoloWindow = { focusIfOpen: vi.fn(async () => true) };
        await activateRow(ctrl as never, addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect((win.SoloWindow as any).focusIfOpen).toHaveBeenCalledWith('ses_a');
        expect((win.API as any).getSession).not.toHaveBeenCalled();
    });

    test('a row with no session id is adopted and announced with session-created', async () => {
        const seen: CustomEvent[] = [];
        const on = (e: Event): void => { seen.push(e as CustomEvent); };
        window.addEventListener('session-created', on);
        (win.API as any).adoptSession = vi.fn(async () => ({ session: { id: 'adopted' }, initial_scrollback_b64: 'QQ==', fifo_start_offset: 12 }));
        await activateRow(ctrl as never, addRow('ext_one'));
        window.removeEventListener('session-created', on);
        expect((win.API as any).adoptSession).toHaveBeenCalledWith('ext_one', true);
        expect(seen[0]!.detail).toEqual({ session: { id: 'adopted' }, initialScrollbackB64: 'QQ==', fifoStartOffset: 12, adopted: true });
    });

    test('a click superseded during the fetch paints nothing over the newer pick', async () => {
        win.NavigationGeneration = { begin: () => 1, isCurrent: () => false, keep: () => false };
        await activateRow(ctrl as never, addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect((win.App as any).returnToExistingTerminal).not.toHaveBeenCalled();
        expect(ctrl._closeAfterSwitch).not.toHaveBeenCalled();
    });

    test('a failed switch alerts with the catalog sentence and clears the pending pick', async () => {
        const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
        const err = vi.spyOn(console, 'error').mockImplementation(() => {});
        (win.API as any).getSession = vi.fn(async () => { throw new Error('boom'); });
        await activateRow(ctrl as never, addRow('cloude_a', { 'data-session-id': 'ses_a' }));
        expect(alert).toHaveBeenCalledTimes(1);
        expect(String(alert.mock.calls[0]![0])).toContain('boom');
        expect(ctrl._pendingSelection).toBeNull();
        alert.mockRestore();
        err.mockRestore();
    });
});

describe('paintSelection', () => {
    test('a pending pick wins; then an open Layout; then the attached session', () => {
        const a = addRow('cloude_a');
        const b = addRow('cloude_b');
        const l = addRow('layout:u1');
        ctrl._activeTmuxName = 'cloude_a';
        ctrl._pendingSelection = { name: 'cloude_b', nav: 1 };
        paintSelection(ctrl as never);
        expect([a, b, l].map((r) => r.getAttribute('aria-selected'))).toEqual(['false', 'true', 'false']);
        ctrl._pendingSelection = null;
        win.CloudeWeb = { layoutPage: { isActive: () => true, current: () => ({ uuid: 'u1' }) } };
        paintSelection(ctrl as never);
        expect([a, b, l].map((r) => r.getAttribute('aria-selected'))).toEqual(['false', 'false', 'true']);
        win.CloudeWeb = undefined;
        paintSelection(ctrl as never);
        expect([a, b, l].map((r) => r.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false']);
    });

    test('while the shell drew the list the shell paints the selection', () => {
        const shellPaint = vi.fn();
        win.CloudeWeb = { sidebarShell: { drew: () => true, paintSelection: shellPaint } };
        paintSelection(ctrl as never);
        expect(shellPaint).toHaveBeenCalledWith(ctrl);
    });
});

describe('onRowActionClick', () => {
    function button(name: string, action: string, inRow: HTMLElement | null): HTMLElement {
        const btn = document.createElement('button');
        btn.setAttribute('data-session-action', action);
        btn.setAttribute('data-session-name', name);
        (inRow ?? document.body).append(btn);
        return btn;
    }

    test('restart opens the picker flow and never confirms or destroys', async () => {
        vi.mocked(runRestartFlow).mockImplementation(rec('runRestart') as never);
        const row = addRow('cloude_a', { 'data-active': '1' });
        await onRowActionClick(ctrl as never, button('cloude_a', 'restart', row));
        expect(calls[0]).toEqual(['runRestart', ctrl, 'cloude_a', row]);
        expect((win.SessionRowActions as any).confirm).not.toHaveBeenCalled();
    });

    test('this tab\'s own session closes through the terminal, with the action passed through', async () => {
        win.TerminalController = { destroySession: vi.fn(async () => {}) };
        await onRowActionClick(ctrl as never, button('cloude_a', 'remove', addRow('cloude_a', { 'data-active': '1' })));
        expect((win.TerminalController as any).destroySession).toHaveBeenCalledWith('remove');
        expect(ctrl._closeAfterSwitch).toHaveBeenCalledTimes(1);
        expect((win.API as any).destroySession).not.toHaveBeenCalled();
    });

    test('a button mounted outside the row finds the live row by name', async () => {
        addRow('cloude_a', { 'data-session-id': 'ses_a' });
        await onRowActionClick(ctrl as never, button('cloude_a', 'close', null));
        expect((win.API as any).destroySession).toHaveBeenCalledWith('ses_a');
        expect(ctrl._lastSig).toBeNull();
        expect(ctrl._fetchAndRender).toHaveBeenCalledTimes(1);
    });

    test('a row with no session id is destroyed by name; a declined confirm does nothing', async () => {
        const row = addRow('ext_one');
        await onRowActionClick(ctrl as never, button('ext_one', 'close', row));
        expect((win.API as any).destroyExternalSession).toHaveBeenCalledWith('ext_one');
        (win.SessionRowActions as any).confirm = vi.fn(async () => false);
        (win.API as any).destroyExternalSession.mockClear();
        await onRowActionClick(ctrl as never, button('ext_one', 'close', row));
        expect((win.API as any).destroyExternalSession).not.toHaveBeenCalled();
    });

    test('a failed destroy alerts with the action and the reason', async () => {
        const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
        const err = vi.spyOn(console, 'error').mockImplementation(() => {});
        (win.API as any).destroySession = vi.fn(async () => { throw new Error('nope'); });
        const row = addRow('cloude_a', { 'data-session-id': 'ses_a' });
        await onRowActionClick(ctrl as never, button('cloude_a', 'close', row));
        expect(String(alert.mock.calls[0]![0])).toMatch(/close.*nope/);
        alert.mockRestore();
        err.mockRestore();
    });
});
