/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import type { RowHost } from './row-host';
import { buildRowPlan, type SessionRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const MOON = 'M21.5 14.6A10 10 0 0 1 9.4 2.5a10 10 0 1 0 12.1 12.1Z';
const CHEVRON = 'M3 8.5 7 4.5 11 8.5';
const css = fs.readFileSync(path.join(__dirname, 'row-polish.css'), 'utf8');

describe('sidebar row polish', () => {
    let container: HTMLElement;
    let component: unknown;

    afterEach(() => {
        if (component) unmount(component as never);
        container?.remove();
    });

    function render(over: Record<string, unknown>, leader = true): HTMLElement {
        container = document.body.appendChild(document.createElement('div'));
        const row = { name: 'cloude_a', status: 'idle', agent_family: 'claude', session_id: 'ses_1', ...over };
        const plan = buildRowPlan(row as never, 'cozy', undefined, null, {} as RowHost) as SessionRowPlan;
        if (leader) plan.leader = { rank: 'project', label: 'project leader' };
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
        return container;
    }

    it('a sleeping lead row keeps its rank insignia and its status light, with no separate sleep glyph', () => {
        const root = render({ asleep: true, status: 'asleep' });
        const slot = root.querySelector('.session-sidebar-row-leader')!;
        expect(slot.innerHTML).toContain(CHEVRON);
        expect(slot.innerHTML).not.toContain(MOON);
        expect(root.querySelector('.status-led, .status-dot')).not.toBeNull();
        expect(root.querySelector('.session-sidebar-row-led-spacer')).toBeNull();
        expect(root.querySelector('.session-sidebar-row-sleeping-icon')).toBeNull();
    });

    it('a sleeping and an awake non-lead row draw the same elements before the name, so nothing shifts', () => {
        const afterProvider = (root: HTMLElement): string => root.querySelector('.session-sidebar-row-provider')!.nextElementSibling?.className ?? '';
        const awake = afterProvider(render({ asleep: false }, false));
        unmount(component as never); component = null; container.remove();
        const asleep = afterProvider(render({ asleep: true, status: 'asleep' }, false));
        expect(asleep).toEqual(awake);
    });

    it('do not disturb draws no badge (#2604); a lead still draws the star', () => {
        const root = render({ do_not_disturb: true }, false);
        expect(root.querySelector('.session-sidebar-row-provider[data-dnd], .session-sidebar-row-provider__dnd')).toBeNull();
        expect(css).not.toMatch(/data-dnd|__dnd/);
        const both = render({ do_not_disturb: true, task_lead: true }, false);
        expect(both.querySelector('.session-sidebar-row-provider[data-role-lead] .session-sidebar-row-provider__lead')).not.toBeNull();
        expect(both.querySelector('.session-sidebar-row-provider[data-dnd], .session-sidebar-row-provider__dnd')).toBeNull();
    });

    it('a row lights up and shows the pointer on hover, with no shift', () => {
        expect(css).toMatch(/\.session-sidebar-row\[role="option"\]:not\(\[aria-selected="true"\]\):hover \{[^}]*background: color-mix/);
        expect(css).not.toMatch(/translate|margin-left|padding-left/);
    });
});
