/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const authFetch = vi.hoisted(() => vi.fn(async (_path: string, _init?: RequestInit) => ({})));
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({ ...(await original<Record<string, unknown>>()), authFetch }));

import AccountMenu from './AccountMenu.svelte';
import * as Bar from '../drawer/bar';
import { accountChip, closeAccountMenu } from './account-menu.svelte';
import { cplugEnablement } from '../../cplugs/host/enablement.svelte';
import { cplugAccountMenuItems } from '../../cplugs/host/readers';
import { beastStatus } from '../beast-mode/control.svelte';
import type { CplugManifest, CplugWeb } from '../../cplugs/sdk';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

let mounted: ReturnType<typeof mount> | null = null;

beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div><div id="acct"></div>';
    Bar.reset();
    accountChip.identity = { kind: 'member', name: 'Joe', provider: 'github' };
    authFetch.mockClear();
});

afterEach(() => {
    closeAccountMenu();
    flushSync();
    if (mounted) unmount(mounted);
    mounted = null;
    accountChip.identity = null;
    beastStatus.data = null;
    cplugEnablement.enabled = {};
});

function openMenu(): void {
    Bar.paint();
    mounted = mount(AccountMenu, { target: document.getElementById('acct')! });
    document.querySelector<HTMLElement>('[data-bar-action="account"]')!.click();
    flushSync();
}

const item = (id: string): HTMLElement | undefined =>
    [...document.querySelectorAll<HTMLElement>('[role="menu"] [role^="menuitem"]')].find((i) => i.dataset.node === id);

describe('plugin account menu items', () => {
    test('the reader offers an item only while its plugin is on and the item is visible', () => {
        const state = { show: true };
        const fake: CplugWeb = {
            id: 'fake', manifest: { id: 'fake', default_enabled: true } as unknown as CplugManifest,
            accountMenuItems: [{ id: 'x', icon: 'bolt', label: () => 'x', visible: () => state.show, run: () => undefined }],
        };
        expect(cplugAccountMenuItems([fake]).map((i) => `${i.cplugId}.${i.id}`)).toEqual(['fake.x']);
        state.show = false;
        expect(cplugAccountMenuItems([fake])).toEqual([]);
        state.show = true;
        cplugEnablement.enabled = { fake: false };
        expect(cplugAccountMenuItems([fake])).toEqual([]);
    });

    test('the beast switch shows its armed state, and no plugin switch can hide it', () => {
        beastStatus.data = { enabled: true, prompts: false, since: null, until: null, pending_count: 0 };
        openMenu();
        const sw = item('beast_mode')!;
        expect(sw.getAttribute('role')).toBe('menuitemcheckbox');
        expect(sw.getAttribute('aria-checked')).toBe('true');
        expect(sw.textContent).toContain('beast mode');
        closeAccountMenu();
        flushSync();
        cplugEnablement.enabled = { beastmode: false };
        document.querySelector<HTMLElement>('[data-bar-action="account"]')!.click();
        flushSync();
        expect(item('beast_mode'), 'beast mode is not a plugin: still there').toBeDefined();
    });

    test('armed with an auto-off, the row says to when in words that fit; disarmed with a beast off box ticked, it says so', () => {
        beastStatus.data = { enabled: true, prompts: false, since: null, until: '2026-10-14T10:56:00Z', pending_count: 0 };
        openMenu();
        expect(item('beast_mode')!.textContent).toMatch(/beast mode, to \d\d:\d\d/);
        closeAccountMenu();
        flushSync();
        beastStatus.data = { enabled: false, since: null, pending_count: 0, auto_off_rows: ['claude_permission'] };
        document.querySelector<HTMLElement>('[data-bar-action="account"]')!.click();
        flushSync();
        const sw = item('beast_mode')!;
        expect(sw.textContent).toContain('beast off, auto approving');
        expect(sw.getAttribute('aria-checked')).toBe('false');
    });

    test('armed, a click disarms through the route and leaves the menu open', async () => {
        beastStatus.data = { enabled: true, prompts: true, since: null, until: null, pending_count: 0 };
        openMenu();
        item('beast_mode')!.click();
        flushSync();
        await vi.waitFor(() => expect(authFetch).toHaveBeenCalledWith('/beast-mode', expect.objectContaining({ method: 'PUT' })));
        const body = JSON.parse(String(authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')![1]!.body));
        expect(body).toEqual({ enabled: false });
        expect(document.querySelector('[role="menu"]'), 'a disarm keeps the menu open').not.toBeNull();
    });

    test('disarmed, a click closes the menu and opens the arm confirmation, which never arms on its own', async () => {
        beastStatus.data = { enabled: false, prompts: false, since: null, until: null, pending_count: 2 };
        authFetch.mockImplementation(async () => ({ ...beastStatus.data }));
        openMenu();
        item('beast_mode')!.click();
        flushSync();
        expect(document.querySelector('[role="menu"]')).toBeNull();
        await vi.waitFor(() => expect(document.querySelector('[data-beast-confirm-go]')).not.toBeNull());
        expect(document.querySelector('[data-beast-risk]')!.textContent).toMatch(/nobody is checking/);
        const hours = [...document.querySelectorAll('[data-beast-auto-off] option')].map((o) => o.textContent);
        expect(hours.slice(1), 'the plural auto-off words get their count').toEqual(['after 1 hour', 'after 4 hours', 'after 8 hours']);
        expect(authFetch.mock.calls.some((c) => c[1]?.method === 'PUT'), 'opening the confirmation writes nothing').toBe(false);
        authFetch.mockImplementation(async () => ({}));
    });
});

describe('checkbox rows stay open (#1710)', () => {
    test('master all flips in place, the menu stays open and the box reads the new state', () => {
        let on = false;
        const g = globalThis as unknown as { CloudeWeb?: Record<string, unknown> };
        const before = g.CloudeWeb;
        g.CloudeWeb = { masterAllEnabled: () => on, setMasterAll: (v: boolean) => { on = v; } };
        try {
            openMenu();
            expect(item('master_all')!.getAttribute('aria-checked')).toBe('false');
            item('master_all')!.click();
            flushSync();
            expect(on).toBe(true);
            expect(document.querySelector('[role="menu"]'), 'a checkbox keeps the menu open').not.toBeNull();
            expect(item('master_all')!.getAttribute('aria-checked')).toBe('true');
        } finally {
            g.CloudeWeb = before;
        }
    });
});
