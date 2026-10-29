/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

describe('a parked sub-agent names itself in the drawer row LED tooltip', () => {
    let container: HTMLElement;
    let component: unknown;

    beforeEach(() => {
        setDrawerEnv({ PreferenceBridge: { read: () => ({ compact: { shells: true } }) } });
    });

    afterEach(() => {
        setDrawerEnv(null);
        if (component) unmount(component as never);
        container?.remove();
    });

    it('appends parked_summary to the LED title, and drops it when absent', () => {
        const summary =
            "background shell bvzswz5xr from sub-agent 'build offsite deploy', running 19h";
        container = document.body.appendChild(document.createElement('div'));
        const plan = buildRowPlan(
            {
                name: 'cloude_a', status: 'working_subagent', agent_family: 'claude',
                parked_summary: summary,
            },
            'compact', undefined, null, {} as RowHost,
        );
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();

        const led = container.querySelector('.status-led');
        expect(led).not.toBeNull();
        expect(led!.getAttribute('title')).toContain(summary);
        expect(led!.getAttribute('aria-label')).toContain(summary);
        expect(led!.getAttribute('title')).not.toMatch(/\.output|\/tasks\//);

        const badge = container.querySelector('.session-sidebar-row-shells-icon');
        expect(badge).not.toBeNull();
        expect(badge!.getAttribute('title')).toBe(summary);

        unmount(component as never);
        container.remove();

        container = document.body.appendChild(document.createElement('div'));
        const bare = buildRowPlan(
            { name: 'cloude_a', status: 'working_subagent', agent_family: 'claude' },
            'compact', undefined, null, {} as RowHost,
        );
        component = mount(SessionRow, { target: container, props: { p: bare as never } });
        flushSync();
        const bareLed = container.querySelector('.status-led');
        expect(bareLed!.getAttribute('title')).not.toContain('sub-agent');
        expect(container.querySelector('.session-sidebar-row-shells-icon')).toBeNull();
    });
});
