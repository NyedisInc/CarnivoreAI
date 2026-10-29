/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { addRows } from '../drawer/asleep';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import { wakeTitle } from './row-chips';
import SessionRow from './SessionRow.svelte';

describe('drawer row wake clock', () => {
    let container: HTMLElement;
    let component: unknown;

    afterEach(() => {
        if (component) unmount(component as never);
        container?.remove();
    });

    function draw(over: Record<string, unknown>): HTMLElement {
        container = document.body.appendChild(document.createElement('div'));
        const row = { name: 'cloude_a', status: 'idle', agent_family: 'claude', session_id: 'ses_1', ...over };
        component = mount(SessionRow, { target: container, props: { p: buildRowPlan(row as never, 'compact', undefined, null, {} as RowHost) as never } });
        flushSync();
        return container;
    }

    it('an asleep row with a wake time draws the clock in the right-hand icon group, the time in its title', () => {
        const el = draw({ status: 'asleep', asleep: true, next_wake_at: 1.9e9 });
        const clock = el.querySelector('.session-sidebar-row-wake-icon');
        expect(clock?.getAttribute('title')).toBe(wakeTitle(1.9e9));
        expect(clock?.getAttribute('title')).toMatch(/^scheduled to wake this session: .+/);
        const cluster = el.querySelector('.session-sidebar-row-controls-cluster');
        expect(clock?.parentElement).toBe(cluster);
        expect(el.querySelector('.session-sidebar-row-main > .session-sidebar-row-wake-icon')).toBeNull();
        const order = Array.from(cluster?.children ?? []);
        expect(order.indexOf(clock as Element)).toBeLessThan(order.findIndex((c) => c.classList.contains('session-row-menu-trigger')) === -1 ? order.length : order.findIndex((c) => c.classList.contains('session-row-menu-trigger')));
        expect(clock?.querySelector('svg')).not.toBeNull();
    });

    it.each([[null], [0], [undefined], ['soon'], [-5]])('an asleep row with next_wake_at %s draws no clock', (at) => {
        expect(draw({ status: 'asleep', asleep: true, next_wake_at: at }).querySelector('.session-sidebar-row-wake-icon')).toBeNull();
    });

    it('a live row never draws it, whatever it carries', () => {
        expect(draw({ next_wake_at: 1.9e9 }).querySelector('.session-sidebar-row-wake-icon')).toBeNull();
    });

    it('the asleep record becomes a row that carries the time (null, never 0, when none)', () => {
        const rows: Array<Record<string, unknown>> = [];
        addRows(rows, [
            { asleep: true, tmux_name: 'carnivore_a', next_wake_at: 1.9e9 },
            { asleep: true, tmux_name: 'carnivore_b', next_wake_at: 0 },
            { asleep: true, tmux_name: 'carnivore_c' },
        ]);
        expect(rows.map((r) => r.next_wake_at)).toEqual([1.9e9, null, null]);
    });
});
