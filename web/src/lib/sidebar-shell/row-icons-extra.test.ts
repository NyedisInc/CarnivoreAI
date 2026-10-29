/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import { loadLegacyDrawer, type LegacyWindow } from './legacy-fixture';
import { rowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

let w: LegacyWindow;

const keptAwake: Record<string, boolean | null> = { cloude_a: true };

beforeAll(() => {
    w = loadLegacyDrawer();
    w.CloudeWeb = {
        ...(w.CloudeWeb || {}),
        autoSleep: { isKeptAwake: (name: string) => (name in keptAwake ? keptAwake[name] : null) },
    };
});

function hideOnCompact(...keys: Array<'cup' | 'pin' | 'menu'>) {
    const compact: Record<string, boolean> = {};
    for (const k of keys) compact[k] = false;
    setDrawerEnv({ PreferenceBridge: { read: () => ({ compact }) } });
}

describe('cup/pin/menu row-icon toggles', () => {
    let container: HTMLElement;
    let component: unknown;

    afterEach(() => {
        if (component) unmount(component as never);
        component = null;
        container?.remove();
        setDrawerEnv(null);
    });

    function renderShell(row: Record<string, unknown>, density = 'compact'): HTMLElement {
        container = document.body.appendChild(document.createElement('div'));
        const plan = buildRowPlan(row as never, density, undefined, null, rowHost());
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
        return container;
    }

    function awakeRow(): Record<string, unknown> {
        return {
            name: 'cloude_a', label: 'a', created_by_cloude: true, status: 'idle',
            agent_family: 'claude', session_id: 'ses_a', session_uuid: 'su-a', kind: 'agent',
        };
    }

    it('cup default (shown) at compact: the cup draws for a kept-awake row', () => {
        setDrawerEnv({});
        const el = renderShell(awakeRow());
        expect(el.querySelector('.session-sidebar-row-keep-awake')).not.toBeNull();
    });

    it('cup hidden: no cup icon, but the name carries a kept-awake note (never a tooltip)', () => {
        hideOnCompact('cup');
        const el = renderShell(awakeRow());
        expect(el.querySelector('.session-sidebar-row-keep-awake')).toBeNull();
        const name = el.querySelector('.session-sidebar-row-name');
        expect(name?.getAttribute('data-name-note')).toContain('kept awake');
        expect(name?.hasAttribute('title')).toBe(false);
    });

    it('cup hidden, but not kept awake: no cup, no note (nothing to report)', () => {
        hideOnCompact('cup');
        const el = renderShell({ ...awakeRow(), name: 'cloude_never_awake' });
        expect(el.querySelector('.session-sidebar-row-keep-awake')).toBeNull();
        const name = el.querySelector('.session-sidebar-row-name');
        expect(name?.getAttribute('data-name-note') || '').not.toContain('kept awake');
    });

    it('pin default (shown) at compact: the pin control draws', () => {
        setDrawerEnv({});
        const el = renderShell(awakeRow());
        expect(el.querySelector('.session-sidebar-row-pin')).not.toBeNull();
    });

    it('pin hidden: no inline pin control', () => {
        hideOnCompact('pin');
        const el = renderShell(awakeRow());
        expect(el.querySelector('.session-sidebar-row-pin')).toBeNull();
    });

    it('menu default (shown) at compact: the kebab draws with no dim modifier', () => {
        setDrawerEnv({});
        const el = renderShell({ ...awakeRow(), status: 'idle' });
        const trigger = el.querySelector('.session-row-menu-trigger');
        expect(trigger).not.toBeNull();
        expect(trigger?.classList.contains('session-row-menu-trigger--dim')).toBe(false);
    });

    it('menu hidden: the kebab stays in the DOM, dimmed', () => {
        hideOnCompact('menu');
        const el = renderShell({ ...awakeRow(), status: 'idle' });
        const trigger = el.querySelector('.session-row-menu-trigger');
        expect(trigger).not.toBeNull();
        expect(trigger?.classList.contains('session-row-menu-trigger--dim')).toBe(true);
        expect(trigger?.getAttribute('data-menu-hidden')).toBe('1');
    });

    it('menu hidden, but an update is ready: the green icon is never dimmed', () => {
        hideOnCompact('menu');
        const el = renderShell({
            ...awakeRow(), status: 'idle',
            agent_update: { ready: true, running: '1.0', installed: '1.1' },
        });
        const trigger = el.querySelector('.session-row-menu-trigger');
        expect(trigger).not.toBeNull();
        expect(trigger?.classList.contains('session-row-menu-trigger--update')).toBe(true);
        expect(trigger?.classList.contains('session-row-menu-trigger--dim')).toBe(false);
        expect(trigger?.hasAttribute('data-menu-hidden')).toBe(false);
    });
});
