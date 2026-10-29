/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const ask = vi.hoisted(() => ({ answer: true, calls: [] as { title: string; message: string }[] }));
vi.mock('../confirm-ok/confirm-ok', async () => {
    const real = await vi.importActual<typeof import('../confirm-ok/confirm-ok')>('../confirm-ok/confirm-ok');
    return { ...real, confirmOk: async (o: { title: string; message: string }) => { ask.calls.push(o); return ask.answer; } };
});
import { middleActionFor, middleClickRow, onRowAuxClick } from './row-middle-click';

const api = {
    sleepSession: vi.fn(async () => ({ status: 'asleep' })),
    killAsleepSession: vi.fn(async () => ({})),
    destroySession: vi.fn(async () => ({})),
    destroyExternalSession: vi.fn(async () => ({})),
};
const menuClose = vi.fn(async () => true);

const ROWS = [
    { name: 'cloude_agent', label: 'agent', session_uuid: 'u-agent', session_id: 'ses_agent', agent_family: 'claude' },
    { name: 'cloude_sleeper', label: 'sleeper', session_uuid: 'u-sleeper', agent_family: 'claude', asleep: true },
    { name: 'cloude_shell', label: 'shell', session_uuid: 'u-shell', session_id: 'ses_shell', agent_family: 'shell' },
    { name: 'browser:7', label: 'page', kind: 'browser' },
    { name: 'layout:l1', label: 'focus', kind: 'layout' },
];

function rowEl(name: string, attrs: Record<string, string> = {}): HTMLElement {
    const el = document.createElement('div');
    el.className = 'session-sidebar-row';
    el.dataset.name = name;
    const row = ROWS.find((r) => r.name === name) as Record<string, unknown>;
    if (row.session_id) el.dataset.sessionId = String(row.session_id);
    if (row.asleep) el.dataset.asleep = '1';
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    document.body.appendChild(el);
    return el;
}

const middle = (target: Element): MouseEvent => {
    const e = new MouseEvent('auxclick', { button: 1, bubbles: true, cancelable: true });
    Object.defineProperty(e, 'target', { value: target });
    return e;
};

const settle = (): Promise<void> => new Promise((r) => setTimeout(r, 20));

describe('sidebar row middle click', () => {
    beforeEach(() => {
        ask.answer = true; ask.calls = [];
        Object.values(api).forEach((f) => f.mockClear()); menuClose.mockClear();
        Object.assign(globalThis, {
            SessionSidebar: { _rows: ROWS, _fetchAndRender: async () => {}, close() {} },
            API: api,
            SessionRowMenuActions: { run: menuClose },
        });
    });
    afterEach(() => { document.body.innerHTML = ''; });

    const none = (): void => {
        expect(api.sleepSession).not.toHaveBeenCalled();
        expect(api.killAsleepSession).not.toHaveBeenCalled();
        expect(api.destroySession).not.toHaveBeenCalled();
        expect(menuClose).not.toHaveBeenCalled();
    };

    it('an awake agent: asks "sleep <name>?", then sleeps it', async () => {
        const e = middle(rowEl('cloude_agent'));
        onRowAuxClick(e);
        await vi.waitFor(() => expect(api.sleepSession).toHaveBeenCalledWith('u-agent'));
        expect(e.defaultPrevented).toBe(true);
        expect(ask.calls[0]!.message).toBe('sleep agent? you can wake it again from its row.');
    });

    it('a sleeping agent: asks "close <name>?", then removes its record, never sleeps it', async () => {
        onRowAuxClick(middle(rowEl('cloude_sleeper')));
        await vi.waitFor(() => expect(api.killAsleepSession).toHaveBeenCalledWith('u-sleeper'));
        expect(ask.calls[0]!.message).toMatch(/^close sleeper\?/);
        expect(api.sleepSession).not.toHaveBeenCalled();
    });

    it('a shell: asks "close <name>?", then destroys the session', async () => {
        onRowAuxClick(middle(rowEl('cloude_shell')));
        await vi.waitFor(() => expect(api.destroySession).toHaveBeenCalledWith('ses_shell'));
        expect(ask.calls[0]!.message).toBe('close shell?');
        expect(api.sleepSession).not.toHaveBeenCalled();
    });

    it.each(['browser:7', 'layout:l1'])('%s: asks "close <name>?", then runs the row menu close', async (name) => {
        onRowAuxClick(middle(rowEl(name, { 'data-kind': name.startsWith('browser') ? 'browser' : 'layout' })));
        await vi.waitFor(() => expect(menuClose).toHaveBeenCalledWith('close', expect.anything()));
        expect(ask.calls[0]!.message).toMatch(/^close /);
    });

    it('a file row: the close runs with the context its kebab carries (the one item menu reads it, not a retired global)', async () => {
        const el = rowEl('browser:7', { 'data-kind': 'browser' });
        el.innerHTML = '<button data-row-menu="browser:7" data-row-menu-kind="browser" data-row-menu-file="1" data-row-menu-label="notes.md"></button>';
        onRowAuxClick(middle(el));
        await vi.waitFor(() => expect(menuClose).toHaveBeenCalled());
        expect(menuClose).toHaveBeenCalledWith('close', expect.objectContaining({ name: 'browser:7', kind: 'browser', isFile: true, label: 'notes.md' }));
    });

    it.each(['cloude_agent', 'cloude_sleeper', 'cloude_shell', 'browser:7', 'layout:l1'])('cancelling (Escape) on %s does nothing', async (name) => {
        ask.answer = false;
        onRowAuxClick(middle(rowEl(name, name.includes(':') ? { 'data-kind': name.startsWith('browser') ? 'browser' : 'layout' } : {})));
        await settle();
        expect(ask.calls).toHaveLength(1);
        none();
    });

    it('a close whose function is missing reports failure, never success (u151-07)', async () => {
        Object.assign(globalThis, { API: {}, SessionRowMenuActions: {} });
        expect(await middleClickRow(rowEl('cloude_sleeper'))).toBe(false);
        expect(await middleClickRow(rowEl('layout:l1', { 'data-kind': 'layout' }))).toBe(false);
    });

    it('a row with no stored session id asks nothing', async () => {
        expect(middleActionFor(document.createElement('div'), { name: 'x', agent_family: 'claude' } as never)).toBe('none');
    });

    it('ignores the right button', async () => {
        const el = rowEl('cloude_agent');
        const e = new MouseEvent('auxclick', { button: 2, cancelable: true });
        Object.defineProperty(e, 'target', { value: el });
        onRowAuxClick(e);
        await settle();
        expect(ask.calls).toHaveLength(0);
    });
});
