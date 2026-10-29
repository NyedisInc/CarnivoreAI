/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import DesktopPanel from './DesktopPanel.svelte';
import { DESKTOP_PREF_DEFAULTS, type DesktopPrefs, type DesktopPrefValues } from './desktop-prefs';
import type { DesktopBridge, DesktopState, NotificationState } from './desktop-bridge';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    delete (globalThis as { carnivoreDesktop?: unknown }).carnivoreDesktop;
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

function fakePrefs(stored: Partial<DesktopPrefValues>, refuse: string | null = null) {
    const doc: Record<string, unknown> = { ...stored };
    const writes: Array<[string, unknown]> = [];
    const prefs: DesktopPrefs = {
        read: (field) => (doc[field] ?? DESKTOP_PREF_DEFAULTS[field]) as never,
        write: async (field, value) => {
            writes.push([field, value]);
            if (refuse) return refuse;
            if (value === null) delete doc[field]; else doc[field] = value;
            return null;
        },
        follow: () => () => {},
    };
    return { prefs, writes };
}

function fakeBridge(state: Partial<DesktopState> & { permission?: NotificationState; waiting?: boolean } = {}) {
    const calls = { open: 0, focus: 0, request: 0, login: [] as Array<[string, boolean]> };
    const full: DesktopState = {
        login: { engine: true, window: false, background: null },
        notifications: { state: state.permission ?? 'not_asked', waiting: state.waiting },
        hotkey: { registered: null, error: null },
        ...state,
    };
    const bridge: DesktopBridge = {
        contract: 1,
        capabilities: ['desktopState', 'setLoginItem', 'requestNotifications', 'openNotificationSettings', 'openFocusSettings'],
        desktopState: async () => full,
        setLoginItem: async (which, enabled) => { calls.login.push([which, enabled]); return { ...full.login, [which]: enabled }; },
        requestNotifications: async () => { calls.request += 1; return { state: 'unknown' }; },
        openNotificationSettings: async () => { calls.open += 1; },
        openFocusSettings: async () => { calls.focus += 1; return 'focus'; },
    };
    return { bridge, calls };
}

async function render(bridge: DesktopBridge | null, prefs: DesktopPrefs, effectiveBind?: string | null): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(DesktopPanel, { target, props: { bridge, prefs, effectiveBind } }));
    await settle();
    return target;
}

const row = (root: HTMLElement, key: string) => root.querySelector<HTMLElement>(`[data-desktop="${key}"]`);

describe('DesktopPanel', () => {
    test('rows follow the fields, and a switch writes its field and shows what the layer then holds', async () => {
        const stored = {
            desktop_banners: true, desktop_banner_hide_command: true, desktop_hotkey: 'Cmd+Option+K', mac_option_is_meta: true,
            desktop_menu_bar_icon: false, desktop_terminal_app: 'custom' as const, desktop_terminal_custom: 'open -a MyTerm',
        };
        const { prefs, writes } = fakePrefs(stored);
        const root = await render(fakeBridge().bridge, prefs);
        expect(row(root, 'banners')!.getAttribute('aria-checked')).toBe('true');
        expect(row(root, 'hide-command')!.getAttribute('aria-checked')).toBe('true');
        expect((row(root, 'hotkey') as HTMLInputElement).value).toBe('Cmd+Option+K');
        expect(row(root, 'option-meta')!.getAttribute('aria-checked')).toBe('true');
        expect(row(root, 'menu-bar-icon')!.getAttribute('aria-checked')).toBe('false');
        expect(row(root, 'terminal')!.querySelector<HTMLInputElement>('input[type="radio"]:checked')!.closest('label')!.textContent).toContain('custom command');
        expect((row(root, 'custom') as HTMLInputElement).value).toBe('open -a MyTerm');
        expect(row(root, 'login-engine')!.getAttribute('aria-checked')).toBe('true');
        expect(row(root, 'login-window')!.getAttribute('aria-checked')).toBe('false');
        expect(row(root, 'bind')!.textContent).toContain('unknown');

        row(root, 'option-meta')!.click();
        await settle();
        expect(writes.at(-1)).toEqual(['mac_option_is_meta', false]);
        expect(row(root, 'option-meta')!.getAttribute('aria-checked')).toBe('false');
    });

    test('a refused write puts the stored value back and says why; login goes through the bridge', async () => {
        const { prefs } = fakePrefs({}, 'that is not an accelerator');
        const { bridge, calls } = fakeBridge();
        const root = await render(bridge, prefs);
        row(root, 'hide-command')!.click();
        await settle();
        expect(row(root, 'hide-command')!.getAttribute('aria-checked')).toBe('false');
        expect(row(root, 'problem')!.textContent).toContain('that is not an accelerator');
        row(root, 'login-window')!.click();
        await settle();
        expect(calls.login).toEqual([['window', true]]);
        expect(row(root, 'login-window')!.getAttribute('aria-checked')).toBe('true');
    });

    test('saving the hotkey asks the shell for its state again, so a registration failure shows at once', async () => {
        const { prefs } = fakePrefs({ desktop_hotkey: 'Cmd+Option+K' });
        const { bridge } = fakeBridge();
        let reads = 0;
        let hotkey = { registered: null as boolean | null, error: null as string | null };
        bridge.desktopState = async () => {
            reads += 1;
            return { login: { engine: true, window: false, background: null }, notifications: { state: 'unknown' }, hotkey };
        };
        const root = await render(bridge, prefs);
        expect(reads).toBe(1);
        expect(row(root, 'hotkey-error')).toBeNull();
        hotkey = { registered: false, error: 'another app already uses it' };
        row(root, 'hotkey-clear')!.click();
        await settle();
        expect(reads).toBe(2);
        expect(row(root, 'hotkey-error')!.textContent).toContain('another app already uses it');
    });

    test('the panel is absent without the capability, and so is the rail section', async () => {
        const { prefs } = fakePrefs({});
        expect(row(await render(null, prefs), 'panel')).toBeNull();
        const noState: DesktopBridge = { contract: 1, capabilities: ['notify'] };
        expect(row(await render(noState, prefs), 'panel')).toBeNull();
        const listedNotThere: DesktopBridge = { capabilities: ['desktopState'] };
        expect(row(await render(listedNotThere, prefs), 'panel')).toBeNull();

        vi.resetModules();
        const without = await import('./settings-registry');
        expect(without.SETTINGS_SECTIONS.some((s) => s.id === 'desktop')).toBe(false);
        (globalThis as { carnivoreDesktop?: unknown }).carnivoreDesktop = fakeBridge().bridge;
        vi.resetModules();
        const withBridge = await import('./settings-registry');
        expect(withBridge.SETTINGS_SECTIONS.find((s) => s.id === 'desktop')).toMatchObject({ screen: 'desktop' });
        expect(withBridge.SETTINGS_SECTIONS.map((s) => s.id).indexOf('desktop')).toBe(withBridge.SETTINGS_SECTIONS.map((s) => s.id).indexOf('general') + 1);
    });

    test('a denied permission shows as denied with the System Settings button; not asked shows none; unknown never says allowed', async () => {
        const { prefs } = fakePrefs({});
        const denied = fakeBridge({ permission: 'denied' });
        const root = await render(denied.bridge, prefs);
        expect(row(root, 'permission')!.getAttribute('data-state')).toBe('denied');
        expect(row(root, 'permission')!.textContent).toContain('denied');
        row(root, 'open-settings')!.click();
        await settle();
        expect(denied.calls.open).toBe(1);

        const fresh = await render(fakeBridge({ permission: 'not_asked' }).bridge, prefs);
        expect(row(fresh, 'permission')!.textContent).toContain('not asked yet');
        expect(row(fresh, 'open-settings')).toBeNull();

        const unknown = await render(fakeBridge({ permission: 'unknown' }).bridge, prefs);
        expect(row(unknown, 'permission')!.textContent).toContain('cannot read');
        expect(row(unknown, 'permission')!.textContent).not.toContain('allowed');
    });

    test('asks-only is a switch on its own field, off by default, and the focus line and button reach the bridge once with no argument (P8, S5, S6)', async () => {
        const { prefs, writes } = fakePrefs({});
        const { bridge, calls } = fakeBridge();
        const spy = vi.spyOn(bridge, 'openFocusSettings');
        const root = await render(bridge, prefs);
        expect(row(root, 'asks-only')!.getAttribute('aria-checked')).toBe('false');
        row(root, 'asks-only')!.click();
        await settle();
        expect(writes.at(-1)).toEqual(['desktop_notify_asks_only', true]);
        expect(row(root, 'asks-only')!.getAttribute('aria-checked')).toBe('true');
        expect(row(root, 'focus-note')!.textContent).toContain('allowed apps');
        row(root, 'open-focus')!.click();
        await settle();
        expect(calls.focus).toBe(1);
        expect(spy).toHaveBeenCalledWith();

        const old: DesktopBridge = { ...bridge, capabilities: ['desktopState'] };
        expect(row(await render(old, prefs), 'open-focus')).toBeNull();
    });

    test('turning banners on with the permission never asked asks main for the one notification', async () => {
        const { prefs, writes } = fakePrefs({});
        const { bridge, calls } = fakeBridge({ permission: 'not_asked' });
        const root = await render(bridge, prefs);
        row(root, 'banners')!.click();
        await settle();
        expect(writes.at(-1)).toEqual(['desktop_banners', true]);
        expect(calls.request).toBe(1);
        expect(row(root, 'permission')!.getAttribute('data-state')).toBe('unknown');
    });

    test('the network rows say the measured bind and the connection state in both outcomes, and never invent either', async () => {
        const { prefs } = fakePrefs({});
        const shellWith = (tls: 'secure' | 'insecure' | 'unknown') => fakeBridge({ network: { tls } }).bridge;

        const local = await render(shellWith('insecure'), prefs, '127.0.0.1');
        expect(row(local, 'bind')!.textContent).toContain('this computer only');
        expect(row(local, 'tls')!.textContent).toContain('nothing leaves it');
        expect(row(local, 'tls')!.textContent).not.toContain('anyone on the network path');

        const wide = await render(shellWith('insecure'), prefs, '0.0.0.0');
        expect(row(wide, 'bind')!.textContent).toContain('every network this computer is on');
        expect(row(wide, 'tls')!.textContent).toContain('anyone on the network path can read it');

        const one = await render(shellWith('secure'), prefs, '192.168.1.20');
        expect(row(one, 'bind')!.textContent).toContain('192.168.1.20 only');
        expect(row(one, 'tls')!.textContent).toContain('encrypted (https)');

        const unmeasured = await render(shellWith('unknown'), prefs, null);
        expect(row(unmeasured, 'bind')!.getAttribute('data-kind')).toBe('unknown');
        expect(row(unmeasured, 'bind')!.textContent).toContain('unknown');
        expect(row(unmeasured, 'tls')!.textContent).toContain('could not measure');

        const oldShell = await render(fakeBridge().bridge, prefs, '127.0.0.1');
        expect(row(oldShell, 'tls')!.textContent).toContain('could not measure');
        expect(row(oldShell, 'network-hint')!.textContent).toContain('settings under remote');
    });

    test('banners on with macOS not yet answered tells the owner to answer the prompt at the top right; allowed, denied and banners off show no hint', async () => {
        const { prefs } = fakePrefs({ desktop_banners: true });
        const waiting = await render(fakeBridge({ permission: 'unknown', waiting: true }).bridge, prefs);
        expect(row(waiting, 'banners-waiting')!.textContent).toContain('top right of the screen');
        expect(row(await render(fakeBridge({ permission: 'unknown', waiting: false }).bridge, prefs), 'banners-waiting')).toBeNull();
        for (const state of ['allowed', 'denied', 'not_asked'] as const) {
            expect(row(await render(fakeBridge({ permission: state }).bridge, prefs), 'banners-waiting')).toBeNull();
        }
        const off = await render(fakeBridge({ permission: 'unknown' }).bridge, fakePrefs({ desktop_banners: false }).prefs);
        expect(row(off, 'banners-waiting')).toBeNull();
    });

    test('banners on with the permission not asked yet says nothing is posted; the partial kinds are always named', async () => {
        const { prefs } = fakePrefs({ desktop_banners: true });
        const root = await render(fakeBridge({ permission: 'not_asked' }).bridge, prefs);
        expect(row(root, 'banners-not-posting')!.textContent).toContain('nothing is posted until you allow them');
        expect(row(root, 'banners-partial')!.textContent).toContain('multi-select');

        const off = await render(fakeBridge({ permission: 'not_asked' }).bridge, fakePrefs({ desktop_banners: false }).prefs);
        expect(row(off, 'banners-not-posting')).toBeNull();
        const asked = await render(fakeBridge({ permission: 'unknown' }).bridge, prefs);
        expect(row(asked, 'banners-not-posting')).toBeNull();
    });
});
