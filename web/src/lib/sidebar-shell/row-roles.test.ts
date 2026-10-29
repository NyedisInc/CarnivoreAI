/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

describe('drawer row role marks', () => {
    let container: HTMLElement;
    let component: unknown;

    afterEach(() => {
        if (component) unmount(component as never);
        container?.remove();
    });

    function provider(over: Record<string, unknown>, density: 'compact' | 'cozy' | 'detailed' = 'compact'): Element {
        container = document.body.appendChild(document.createElement('div'));
        const row = { name: 'cloude_a', status: 'idle', agent_family: 'claude', session_id: 'ses_1', ...over };
        component = mount(SessionRow, { target: container, props: { p: buildRowPlan(row as never, density, undefined, null, {} as RowHost) as never } });
        flushSync();
        return container.querySelector('.session-sidebar-row-provider')!;
    }

    it('lead: the star, its data attribute and its catalog title', () => {
        const p = provider({ task_lead: true, do_not_disturb: null });
        expect(p.getAttribute('data-role-lead')).toBe('1');
        expect(p.hasAttribute('data-dnd')).toBe(false);
        const star = p.querySelector('.session-sidebar-row-provider__lead');
        expect(star?.getAttribute('title')).toBe('project lead');
        expect(star?.querySelector('svg')).not.toBeNull();
        expect(p.querySelector('.session-sidebar-row-provider__dnd')).toBeNull();
    });

    it('do not disturb: the badge alone', () => {
        const p = provider({ task_lead: false, do_not_disturb: true });
        expect(p.getAttribute('data-dnd')).toBe('1');
        expect(p.hasAttribute('data-role-lead')).toBe(false);
        expect(p.querySelector('.session-sidebar-row-provider__dnd')?.getAttribute('title')).toBe('do not disturb: takes no new tasks');
        expect(p.querySelector('.session-sidebar-row-provider__lead')).toBeNull();
    });

    it.each([[null, null], [false, false], [undefined, undefined]])('task_lead %s, do_not_disturb %s: no mark at all', (lead, dnd) => {
        const p = provider({ task_lead: lead, do_not_disturb: dnd });
        expect(p.querySelector('[class*="session-sidebar-row-provider__"]')).toBeNull();
        expect(p.hasAttribute('data-role-lead')).toBe(false);
        expect(p.hasAttribute('data-dnd')).toBe(false);
    });

    it.each(['compact', 'cozy', 'detailed'] as const)('%s: one slot - lead shows the star only (even with dnd on), non-lead dnd shows the badge only, dnd off shows nothing, no crown', (density) => {
        const marks = (over: Record<string, unknown>): string[] =>
            [...provider(over, density).querySelectorAll('[class*="session-sidebar-row-provider__"]')].map((m) => m.className);
        const again = (): void => { unmount(component as never); container.remove(); component = null; };
        expect(marks({ task_lead: true, do_not_disturb: true })).toEqual(['session-sidebar-row-provider__lead']);
        expect(container.querySelector('[data-dnd]')).toBeNull();
        again();
        expect(marks({ task_lead: false, do_not_disturb: true })).toEqual(['session-sidebar-row-provider__dnd']);
        again();
        expect(marks({ task_lead: false, do_not_disturb: false })).toEqual([]);
        expect(container.querySelector('[data-off], [data-size-master], .session-sidebar-row-provider__master')).toBeNull();
    });
});
