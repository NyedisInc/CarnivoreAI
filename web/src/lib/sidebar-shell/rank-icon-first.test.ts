/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const ROW = { name: 'cloude_a', status: 'idle', agent_family: 'claude', session_id: 'ses_1' };

describe('drawer row: the rank insignia is the first icon', () => {
    let container: HTMLElement | undefined;
    let component: unknown;

    afterEach(() => {
        if (component) unmount(component as never);
        container?.remove();
    });

    function firstClasses(density: 'compact' | 'cozy' | 'detailed', ranked: boolean): string[] {
        if (component) unmount(component as never);
        container?.remove();
        container = document.body.appendChild(document.createElement('div'));
        const plan = buildRowPlan(ROW as never, density, undefined, null, {} as RowHost);
        if (ranked && plan.type === 'session') plan.leader = { rank: 'project', label: 'project agent' };
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
        const main = container.querySelector('.session-sidebar-row-main')!;
        return Array.from(main.children).map((c) => c.className.toString());
    }

    for (const density of ['compact', 'cozy', 'detailed'] as const) {
        it(`${density}: a ranked row leads with the insignia, an unranked row keeps its icons`, () => {
            const plain = firstClasses(density, false);
            expect(plain.some((c) => c.includes('session-sidebar-row-leader'))).toBe(false);
            const ranked = firstClasses(density, true);
            expect(ranked[0]).toContain('session-sidebar-row-leader');
            expect(ranked.slice(1)).toEqual(plain);
        });
    }
});
