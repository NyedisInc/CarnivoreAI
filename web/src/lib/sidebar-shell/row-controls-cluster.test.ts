/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import { timerChip } from '../timers/timers';
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
        timerChip,
        autoSleep: { isKeptAwake: (name: string) => (name in keptAwake ? keptAwake[name] : null) },
    };
});

function fullRow(): Record<string, unknown> {
    return {
        name: 'cloude_a', label: 'a', created_by_cloude: true, status: 'working_subagent',
        agent_family: 'claude', session_id: 'ses_a', session_uuid: 'su-a', kind: 'agent',
        is_pinned: true, subagents_running: 2, subagents_total: 3, background_open: 1,
        timers_live: 1, timers_next_fire_at: new Date(Date.now() + 60_000).toISOString(),
    };
}

const CLUSTER = '.session-sidebar-row-controls-cluster';

function clusterSlots(root: HTMLElement): string[] {
    const cluster = root.querySelector(CLUSTER);
    if (!cluster) return [];
    const flat = Array.from(cluster.children).flatMap((el) => (
        el.classList.contains('session-sidebar-row-optional-icons') ? Array.from(el.children) : [el]));
    return flat.map((el) => {
        if (el.classList.contains('session-sidebar-row-agents-icon')) return 'agents-icon';
        if (el.classList.contains('session-sidebar-row-shells-icon')) return 'shells-icon';
        if (el.classList.contains('session-sidebar-row-timers-icon')) return 'timers-icon';
        if (el.classList.contains('session-sidebar-row-automations-icon')) return 'automations-icon';
        if (el.classList.contains('session-sidebar-row-keep-awake')) return 'keep-awake';
        if (el.classList.contains('session-sidebar-row-pin')) return 'pin';
        if (el.classList.contains('session-row-menu-trigger')) return 'kebab';
        if (el.classList.contains('session-sidebar-row-delete')) return 'inline-delete';
        return `unknown:${el.className}`;
    });
}

describe('the sidebar row control cluster (issue #1045)', () => {
    let container: HTMLElement;
    let component: unknown;

    beforeEach(() => {
        setDrawerEnv({ PreferenceBridge: { read: () => ({ compact: { agents: true, shells: true, timers: true } }) } });
    });

    afterEach(() => {
        setDrawerEnv(null);
        if (component) unmount(component as never);
        container?.remove();
    });

    function renderShell(row: Record<string, unknown>): HTMLElement {
        container = document.body.appendChild(document.createElement('div'));
        const plan = buildRowPlan(row as never, 'compact', undefined, null, rowHost());
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
        return container;
    }

    it('agents icon, shells icon, timers icon, cup, pin, kebab, in that order, all inside one wrapper', () => {
        const el = renderShell({ ...fullRow(), spectator_expires_at: null });
        expect(clusterSlots(el)).toEqual(['agents-icon', 'shells-icon', 'timers-icon', 'keep-awake', 'pin', 'kebab']);
    });

    it('shell: the kebab stays the last control with the Carnivore timers icon on too', () => {
        setDrawerEnv({ PreferenceBridge: { read: () => ({ compact: { agents: true, shells: true, timers: true, automations: true } }) } });
        const slots = clusterSlots(renderShell({ ...fullRow(), spectator_expires_at: null, automations_state: 'ok', automations_total: 1, automations_enabled: 1 }));
        expect(slots).toEqual(['agents-icon', 'shells-icon', 'timers-icon', 'automations-icon', 'keep-awake', 'pin', 'kebab']);
        expect(slots[slots.length - 1]).toBe('kebab');
    });

    it('a dead row draws inline restart/remove in the kebab\'s place, still inside the wrapper, still last', () => {
        const dead = { ...fullRow(), status: 'dead', subagents_running: null, background_open: null, timers_live: 0 };
        const slots = clusterSlots(renderShell(dead));
        expect(slots.slice(0, 2)).toEqual(['keep-awake', 'pin']);
        expect(slots.length).toBeGreaterThan(2);
        expect(slots.slice(2).every((s) => s === 'inline-delete')).toBe(true);
        expect(slots).not.toContain('kebab');
    });

    it('hidden icons take no space: none of the three icons draws when there is nothing to show', () => {
        const bare = { name: 'cloude_b', status: 'idle', agent_family: 'claude', session_id: 'ses_b', is_pinned: false };
        expect(clusterSlots(renderShell(bare))).toEqual(['pin', 'kebab']);
    });

    it('wraps every control in one dedicated span, the gap rule\'s hook (client/css/session-sidebar-rows.css)', () => {
        const el = renderShell(fullRow());
        const cluster = el.querySelector(CLUSTER);
        expect(cluster).not.toBeNull();
        expect(cluster!.tagName).toBe('SPAN');
        expect(cluster!.children.length).toBe(4);
    });

    it('the three optional icons share one group, first in the wrapper (issue #1211)', () => {
        const cluster = renderShell(fullRow()).querySelector(CLUSTER)!;
        const group = cluster.firstElementChild!;
        expect(group.className).toBe('session-sidebar-row-optional-icons');
        expect(Array.from(group.children).map((c) => c.className)).toEqual([
            'session-sidebar-row-agents-icon',
            'session-sidebar-row-shells-icon',
            'session-sidebar-row-timers-icon',
        ]);
    });

    it('no optional icon, no group: a bare row draws no empty wrapper', () => {
        const bare = { name: 'cloude_b', status: 'idle', agent_family: 'claude', session_id: 'ses_b', is_pinned: false };
        expect(renderShell(bare).querySelector('.session-sidebar-row-optional-icons')).toBeNull();
    });

    it('the wrapper sits right after the share mark, before any of the cluster controls', () => {
        const el = renderShell({ ...fullRow(), spectator_expires_at: new Date(Date.now() + 3_600_000).toISOString() });
        const main = el.querySelector('.session-sidebar-row-main') as HTMLElement;
        const share = main.querySelector('.session-sidebar-row-share');
        const cluster = main.querySelector(CLUSTER);
        expect(share).not.toBeNull();
        expect(cluster).not.toBeNull();
        expect(share!.nextElementSibling).toBe(cluster);
    });
});
