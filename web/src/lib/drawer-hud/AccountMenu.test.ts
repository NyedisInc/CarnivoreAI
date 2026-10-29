/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import AccountMenu from './AccountMenu.svelte';
import * as Bar from '../drawer/bar';
import { accountChip, accountMenu, closeAccountMenu } from './account-menu.svelte';
import { catalogAccount } from './catalog-account.svelte';

const requireAccount = vi.hoisted(() => vi.fn((_ask: unknown) => Promise.resolve('prompted')));
vi.mock('../carnivore-account/funnel', () => ({ requireAccount }));
const toggleSwarm = vi.hoisted(() => vi.fn(() => Promise.resolve()));
vi.mock('../swarm-switch/control.svelte', async (actual) => ({ ...(await actual<object>()), toggleSwarm }));
import { swarmSwitch } from '../swarm-switch/control.svelte';
import { placeMenuAbove } from '../drawer-tabs/add-component-menu';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

let mounted: ReturnType<typeof mount> | null = null;
const w = window as unknown as Record<string, unknown>;

beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div><div id="acct"></div><p id="elsewhere">x</p>';
    Bar.reset();
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1400 });
    accountChip.identity = { kind: 'member', name: 'Joe', provider: 'github' };
});

afterEach(() => {
    closeAccountMenu();
    flushSync();
    if (mounted) unmount(mounted);
    mounted = null;
    accountChip.identity = null;
    catalogAccount.facts = null;
    swarmSwitch.data = null;
    toggleSwarm.mockClear();
    delete w.CloudeWeb;
    delete w.App;
});

function openMenu(): HTMLElement {
    Bar.paint();
    mounted = mount(AccountMenu, { target: document.getElementById('acct')! });
    const chip = document.querySelector<HTMLElement>('[data-bar-action="account"]')!;
    chip.click();
    flushSync();
    return chip;
}

const menu = (): HTMLElement | null => document.querySelector<HTMLElement>('[role="menu"]');
const items = (): HTMLElement[] =>
    [...document.querySelectorAll<HTMLElement>('[role="menu"] [role^="menuitem"]')];

describe('the account menu', () => {
    test('opens from the chip with every footer action, grouped, and the account in its heading', () => {
        const calls: string[] = [];
        w.CloudeWeb = {
            openSettingsScreen: () => { calls.push('settings'); return true; },
            openDocsScreen: () => { calls.push('help'); return true; },
            layoutEditor: { active: () => false, available: () => true, toggle: () => { calls.push('layout'); } },
            masterAllEnabled: () => false,
            setMasterAll: () => { calls.push('master_all'); },
        };
        const logout = vi.fn();
        w.App = { logout };
        catalogAccount.facts = { signedIn: true, handle: 'Joe', login: 'joe@example.com', email: 'joe@example.com', provider: 'github' };
        const chip = openMenu();
        expect(menu(), 'the chip opened no menu').not.toBeNull();
        expect(chip.getAttribute('aria-expanded')).toBe('true');
        expect(items().map((i) => i.dataset.node)).toEqual(['account_page', 'layout', 'master_all', 'beast_mode', 'signout', 'logout']);
        expect(menu()!.querySelector('.acm-heading')!.textContent, 'the header shows the handle and the email').toBe('Joejoe@example.com');
        expect(menu()!.querySelector('kbd.acm-hint'), 'no hint for a key that is not a global chord').toBeNull();
        const master = items().find((i) => i.dataset.node === 'master_all')!;
        expect(master.getAttribute('role')).toBe('menuitemcheckbox');
        expect(master.getAttribute('aria-checked')).toBe('false');
        expect(master.classList.contains('acm-sep'), 'master all opens its own group').toBe(true);
        expect(items().find((i) => i.dataset.node === 'logout')!.classList.contains('acm-sep')).toBe(true);
        expect(document.activeElement, 'focus moves into the menu').toBe(items()[0]);

        items().find((i) => i.dataset.node === 'layout')!.click();
        flushSync();
        expect(menu(), 'layout closes the menu').toBeNull();
        document.querySelector<HTMLElement>('[data-bar-action="account"]')!.click();
        flushSync();
        items().find((i) => i.dataset.node === 'master_all')!.click();
        flushSync();
        expect(menu(), 'master_all is a checkbox: it stays open (#1710)').not.toBeNull();
        expect(calls).toEqual(['layout', 'master_all']);
        expect(items().find((i) => i.dataset.node === 'logout')!.textContent).toContain('lock this device');
        items().find((i) => i.dataset.node === 'logout')!.click();
        flushSync();
        expect(logout).toHaveBeenCalledTimes(1);
    });

    test('a page opened from the menu puts the slide-over drawer away after the page opens; a toggle does not', () => {
        const order: string[] = [];
        w.CloudeWeb = {
            openSettingsScreen: () => { order.push('settings'); return true; },
            openDocsScreen: () => { order.push('help'); return true; },
            openAccountScreen: () => { order.push('account'); return true; },
            masterAllEnabled: () => false,
            setMasterAll: () => { order.push('master_all'); },
        };
        w.SessionSidebarPin = { closeAfterSwitch: () => { order.push('drawer closed'); } };
        catalogAccount.facts = { signedIn: true, handle: 'Joe', login: 'joe@example.com', email: 'joe@example.com', provider: 'github' };
        openMenu();
        for (const id of ['account_page', 'master_all']) {
            items().find((i) => i.dataset.node === id)!.click();
            flushSync();
            document.querySelector<HTMLElement>('[data-bar-action="account"]')!.click();
            flushSync();
        }
        delete w.SessionSidebarPin;
        expect(order).toEqual(['account', 'drawer closed', 'master_all']);
    });

    test('signed out, the first row is the sign in row, which opens the funnel with src menu', () => {
        accountChip.identity = { kind: 'lurker', name: '', provider: null };
        openMenu();
        expect(items()[0]!.dataset.node).toBe('signin');
        expect(items()[0]!.textContent).toContain('sign in or create your free account');
        expect(items().some((i) => i.dataset.node === 'signout')).toBe(false);
        expect(menu()!.querySelector('.acm-heading')!.textContent).toBe('not signed in');
        items()[0]!.click();
        flushSync();
        expect(requireAccount).toHaveBeenCalledTimes(1);
        expect(requireAccount.mock.calls[0]![0]).toMatchObject({ src: 'menu' });
        expect(menu()).toBeNull();
    });

    test('Escape closes it and gives focus back to the chip', () => {
        const chip = openMenu();
        items()[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
        expect(document.activeElement, 'arrows move through the items').toBe(items()[1]);
        items()[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        flushSync();
        expect(menu()).toBeNull();
        expect(accountMenu.open).toBe(false);
        expect(document.activeElement).toBe(chip);
        expect(chip.getAttribute('aria-expanded')).toBe('false');
    });

    test('a press outside closes it', () => {
        openMenu();
        document.getElementById('elsewhere')!.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
        flushSync();
        expect(menu()).toBeNull();
    });

    test('a repaint under the open menu moves it onto the new chip', () => {
        openMenu();
        accountChip.identity = { kind: 'member', name: 'work', provider: 'email' };
        Bar.paint();
        flushSync();
        const chip = document.querySelector<HTMLElement>('[data-bar-action="account"]')!;
        expect(accountMenu.anchor).toBe(chip);
        expect(chip.getAttribute('aria-expanded')).toBe('true');
    });

    test('edit layout stays on a screen with nothing to edit, inert with its reason', () => {
        w.CloudeWeb = { layoutEditor: { active: () => false, available: () => false, toggle: vi.fn() } };
        openMenu();
        const layout = items().find((i) => i.dataset.node === 'layout')!;
        expect(layout.getAttribute('aria-disabled')).toBe('true');
        expect(layout.getAttribute('data-tooltip')).toContain('open a terminal screen');
        expect(layout.getAttribute('aria-description')).toContain('open a terminal screen');
    });

    test('NEGATIVE: no bridges, no layout and no master all; no known account reads as a lurker', () => {
        accountChip.identity = null;
        openMenu();
        expect(items().map((i) => i.dataset.node)).toEqual(['signin', 'beast_mode', 'logout']);
        expect(menu()!.querySelector('.acm-heading')!.textContent).toBe('not signed in');
    });
});

describe('the global swarm switch in the SysOp menu (Joe (ccsliinc), 2026-10-15, docs/swarm.md 4.10)', () => {
    test('a toggle row after master all, checked as the server says, that flips and stays open', () => {
        w.CloudeWeb = { masterAllEnabled: () => false, setMasterAll: () => {} };
        swarmSwitch.data = { enabled: false };
        openMenu();
        expect(items().map((i) => i.dataset.node)).toEqual(['account_page', 'master_all', 'swarm', 'beast_mode', 'signout', 'logout']);
        const swarm = items().find((i) => i.dataset.node === 'swarm')!;
        expect(swarm.getAttribute('role')).toBe('menuitemcheckbox');
        expect(swarm.getAttribute('aria-checked'), 'off reads unchecked').toBe('false');
        expect(swarm.textContent).toContain('swarm');
        swarm.click();
        flushSync();
        expect(toggleSwarm).toHaveBeenCalledTimes(1);
        expect(menu(), 'a flip keeps the menu open').not.toBeNull();
        swarmSwitch.data = { enabled: true };
        flushSync();
        expect(items().find((i) => i.dataset.node === 'swarm')!.getAttribute('aria-checked'), 'the pushed state repaints the row').toBe('true');
    });

    test('NEGATIVE: no answer from the server yet, no row (never a guessed state)', () => {
        openMenu();
        expect(items().some((i) => i.dataset.node === 'swarm')).toBe(false);
    });
});

describe('the account menu holds the account and quick actions only (issue #1774, spec T13)', () => {
    test('never a destination the menu slide-out or the rail gear offers', () => {
        w.CloudeWeb = {
            openSettingsScreen: () => true,
            openDocsScreen: () => true,
            layoutEditor: { active: () => false, available: () => true, toggle: vi.fn() },
            masterAllEnabled: () => false,
            setMasterAll: vi.fn(),
        };
        openMenu();
        const ids = items().map((i) => i.dataset.node);
        expect(ids).toEqual(['account_page', 'layout', 'master_all', 'beast_mode', 'signout', 'logout']);
        expect(ids).not.toContain('settings');
        expect(ids).not.toContain('help');
        expect(ids).not.toContain('sidebar_layout');
    });
});

describe('the menu opens upward', () => {
    test('its bottom sits over the chip, its left edge on the chip', () => {
        expect(placeMenuAbove({ left: 10, top: 860, right: 120, bottom: 884 }, { width: 220, height: 200 }, { width: 1440, height: 900 }))
            .toEqual({ left: 10, top: 656, maxHeight: 848 });
    });

    test('taller than the room above, it pins to the top edge and scrolls', () => {
        expect(placeMenuAbove({ left: 10, top: 100, right: 120, bottom: 124 }, { width: 220, height: 400 }, { width: 1440, height: 900 }))
            .toEqual({ left: 10, top: 8, maxHeight: 88 });
    });
});
