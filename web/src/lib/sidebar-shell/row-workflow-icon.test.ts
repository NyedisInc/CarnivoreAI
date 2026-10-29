/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

describe('drawer row workflow mark', () => {
    let container: HTMLElement;
    let component: unknown;

    afterEach(() => {
        if (component) unmount(component as never);
        container?.remove();
    });

    function render(density: string, over: Record<string, unknown>): HTMLElement {
        container = document.body.appendChild(document.createElement('div'));
        const row = { name: 'cloude_a', status: 'working', agent_family: 'claude', session_id: 'ses_1', ...over };
        const plan = buildRowPlan(row as never, density, undefined, null, {} as RowHost);
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
        return container;
    }

    it.each(['compact', 'cozy', 'detailed'])('draws while a workflow runs, at %s, with no subagents', (density) => {
        const icon = render(density, { workflow_active: true, subagents_running: 0 })
            .querySelector('.session-sidebar-row-workflow-icon');
        expect(icon).not.toBeNull();
        expect(icon!.getAttribute('title')).toBe('running a workflow');
        expect(icon!.querySelector('svg')).not.toBeNull();
        expect(icon!.nextElementSibling?.getAttribute('data-pin-session')).not.toBeNull();
    });

    it.each([null, false, undefined])('draws nothing for workflow_active %s', (v) => {
        expect(render('cozy', { workflow_active: v }).querySelector('.session-sidebar-row-workflow-icon')).toBeNull();
    });
});
