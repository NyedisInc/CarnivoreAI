/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

describe('drawer row icons: agents, shells and timers', () => {
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

    function renderRow(row: Record<string, unknown>): HTMLElement {
        container = document.body.appendChild(document.createElement('div'));
        const plan = buildRowPlan(row as never, 'compact', undefined, null, {} as RowHost);
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
        return container;
    }

    it('draws the agents icon for a running subagent, with the count in its title', () => {
        const el = renderRow({
            name: 'cloude_a', status: 'working_subagent', agent_family: 'claude',
            session_id: 'ses_1', subagents_running: 2, subagents_total: 3,
        });
        const icon = el.querySelector('.session-sidebar-row-agents-icon');
        expect(icon).not.toBeNull();
        expect(icon!.getAttribute('title')).toBe('2 agents running, 3 launched in this conversation');
        expect(icon!.getAttribute('role')).toBe('img');
        expect(icon!.textContent).toBe('');
    });

    it('drops the agents icon when nothing is running, regardless of a parked shell', () => {
        const summary = "background shell bvzswz5xr from sub-agent 'build offsite deploy', running 19h";
        const el = renderRow({
            name: 'cloude_a', status: 'working_subagent', agent_family: 'claude', parked_summary: summary,
        });
        expect(el.querySelector('.session-sidebar-row-agents-icon')).toBeNull();
    });

    it('draws the shells icon from background_open, joined with the parked summary', () => {
        const summary = 'polling :5011';
        const el = renderRow({
            name: 'cloude_a', status: 'working_subagent', agent_family: 'claude',
            background_open: 2, parked_summary: summary,
        });
        const icon = el.querySelector('.session-sidebar-row-shells-icon');
        expect(icon).not.toBeNull();
        expect(icon!.getAttribute('title')).toBe(`2 shells running: ${summary}`);
        expect(icon!.getAttribute('role')).toBe('img');
        expect(icon!.textContent).toBe('');
    });

    it('draws the shells icon from the parked summary alone when the count is not measured', () => {
        const summary = "background shell bvzswz5xr from sub-agent 'build offsite deploy', running 19h";
        const el = renderRow({
            name: 'cloude_a', status: 'working_subagent', agent_family: 'claude', parked_summary: summary,
        });
        const icon = el.querySelector('.session-sidebar-row-shells-icon');
        expect(icon).not.toBeNull();
        expect(icon!.getAttribute('title')).toBe(summary);
    });

    it('the agents and shells icons are independent: both can draw at once', () => {
        const el = renderRow({
            name: 'cloude_a', status: 'working_subagent', agent_family: 'claude',
            session_id: 'ses_1', subagents_running: 1, background_open: 1,
        });
        expect(el.querySelector('.session-sidebar-row-agents-icon')).not.toBeNull();
        expect(el.querySelector('.session-sidebar-row-shells-icon')).not.toBeNull();
    });

    it('draws none of the three icons when there is nothing to show', () => {
        const el = renderRow({ name: 'cloude_a', status: 'idle', agent_family: 'claude' });
        expect(el.querySelector('.session-sidebar-row-agents-icon')).toBeNull();
        expect(el.querySelector('.session-sidebar-row-shells-icon')).toBeNull();
        expect(el.querySelector('.session-sidebar-row-timers-icon')).toBeNull();
    });

    it('draws the timers icon while a timer is live, with the count and next-fire time in its title', () => {
        const soon = new Date(Date.now() + 18 * 60 * 1000).toISOString();
        const el = renderRow({
            name: 'cloude_a', status: 'idle', agent_family: 'claude',
            timers_live: 1, timers_next_fire_at: soon,
        });
        const icon = el.querySelector('.session-sidebar-row-timers-icon');
        expect(icon).not.toBeNull();
        expect(icon!.getAttribute('title')).toMatch(/^1 live timer, next fires in \d+m$/);
        expect(icon!.getAttribute('role')).toBe('img');
        expect(icon!.textContent).toBe('');
    });

    it('drops the timers icon once the live count is back to zero', () => {
        const el = renderRow({
            name: 'cloude_a', status: 'idle', agent_family: 'claude', timers_live: 0,
        });
        expect(el.querySelector('.session-sidebar-row-timers-icon')).toBeNull();
    });
});
