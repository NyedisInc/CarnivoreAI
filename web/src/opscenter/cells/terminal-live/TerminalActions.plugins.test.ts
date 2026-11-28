/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const authFetchMock = vi.hoisted(() => vi.fn(async () => ({ ok: true })));
const selectMock = vi.hoisted(() => vi.fn());

vi.mock('./actions', () => ({ terminalAction: vi.fn(), toolShowing: () => false }));
vi.mock('../../api', () => ({
    sessions: {
        data: [{ session: { id: 'ses_second' }, tmux_session: 'cloude_second', pinned_theme: 'matrix', agent_type: 'claude' }],
        refresh: vi.fn(),
    },
    asleep: { refresh: vi.fn() },
    sleepSession: vi.fn(),
}));
vi.mock('../../api/auth.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../api/auth.svelte')>();
    return {
        ...actual,
        auth: { ...actual.auth, state: 'signed-in' },
        authFetch: authFetchMock,
    };
});
vi.mock('../../api/host', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../api/host')>();
    return { ...actual, primarySessionId: () => '' };
});
vi.mock('../../lib/input-focus.svelte', () => ({
    inputFocus: { select: selectMock, claim: vi.fn() },
}));
vi.mock('./row-menu', () => ({
    closeRowMenu: vi.fn(),
    openRowMenu: vi.fn(() => false),
    uuidOfTmuxName: () => 'uuid-second',
}));

import TerminalActions from './TerminalActions.svelte';
import { pluginsStore, type SlotContribution, type StoreCplugRow } from '../../../lib/plugins/store.svelte';

function makeRow(overrides: Partial<StoreCplugRow> = {}): StoreCplugRow {
    return {
        id: 'acme.term',
        name: 'Acme Term',
        enabled: true,
        state: 'active',
        runtime_paused: false,
        granted_ui_slots: ['terminal.toolbar'],
        routes: ['snap'],
        declared_tools: ['run_lint'],
        ...overrides,
    };
}

function seedStore(rows: StoreCplugRow[], slots: Record<string, SlotContribution[]>): void {
    pluginsStore.rows = rows;
    pluginsStore.read = true;
    pluginsStore.slots = slots;
    pluginsStore.slotsRead = true;
}

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
    pluginsStore.resetForTest();
    authFetchMock.mockClear();
    selectMock.mockClear();
});

afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    pluginsStore.resetForTest();
    document.body.replaceChildren();
    vi.restoreAllMocks();
});

function setup(width: number): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(TerminalActions, { target, props: { slot: 'terminal:second', sessionId: 'ses_second', width } }));
    flushSync();
    const menu = target.querySelector('.cell-options') as HTMLElement | null;
    if (menu) menu.hidePopover = vi.fn();
    return target;
}

test('acquires slots, places strip vs position:menu controls at wide width, and folds all below 420px', async () => {
    const acquireSpy = vi.spyOn(pluginsStore, 'acquire').mockImplementation(() => () => {});
    seedStore(
        [
            makeRow(),
            makeRow({ id: 'noconsent.term', granted_ui_slots: [] }),
        ],
        {
            'terminal.toolbar': [
                {
                    plugin_id: 'acme.term',
                    install_key: 'acme.term',
                    slot: 'terminal.toolbar',
                    declared_slot: 'terminal.toolbar',
                    item: { id: 'lint', label: 'Lint', tooltip: 'Run Lint', tool: 'run_lint', icon: 'cube' },
                },
                {
                    plugin_id: 'acme.term',
                    install_key: 'acme.term',
                    slot: 'terminal.toolbar',
                    declared_slot: 'terminal.toolbar',
                    item: { id: 'snap', label: 'Snapshot', route: 'snap', position: 'menu' },
                },
                {
                    plugin_id: 'noconsent.term',
                    install_key: 'noconsent.term',
                    slot: 'terminal.toolbar',
                    declared_slot: 'terminal.toolbar',
                    item: { id: 'hidden', label: 'Hidden', route: 'snap' },
                },
            ],
        },
    );

    const wide = setup(900);
    expect(acquireSpy).toHaveBeenCalledWith({ includeSlots: true });

    const stripBtn = wide.querySelector<HTMLButtonElement>('.cell-tools [data-cplug-tool="acme.term:lint"]')!;
    expect(stripBtn).toBeTruthy();
    expect(stripBtn.getAttribute('data-button-root')).toBe('true');
    expect(wide.querySelector('.cell-tools [data-cplug-tool="acme.term:snap"]')).toBeNull();
    expect(wide.querySelector('.cell-options [data-cplug-tool="acme.term:snap"][role="menuitem"]')).toBeTruthy();
    expect(wide.querySelector('[data-cplug-tool="noconsent.term:hidden"]')).toBeNull();

    const down = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
    stripBtn.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);

    stripBtn.click();
    expect(selectMock).toHaveBeenCalledWith('terminal:second');
    await vi.waitFor(() => expect(authFetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = authFetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/cplug-owner/tool');
    expect(JSON.parse(String(init.body))).toEqual({
        cplug_id: 'acme.term',
        tool: 'run_lint',
        args: {},
        session_ref: 'uuid-second',
    });

    const narrow = setup(360);
    expect(narrow.querySelector('.cell-tools [data-cplug-tool="acme.term:lint"]')).toBeNull();
    const folded = narrow.querySelector<HTMLButtonElement>('.cell-options [data-cplug-tool="acme.term:lint"][role="menuitem"]')!;
    expect(folded).toBeTruthy();
    folded.click();
    expect(selectMock).toHaveBeenCalledTimes(2);
});
