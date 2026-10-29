/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import { defaultFor, iconVisible } from '../drawer/row-icon-prefs';
import { loadLegacyDrawer } from './legacy-fixture';
import { contextPlan } from './row-context';
import { rowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const row = (pct: number | null | undefined): Record<string, unknown> => ({
    name: 'cloude_a', label: 'a', created_by_cloude: true, status: 'idle',
    agent_family: 'claude', session_id: 'ses_a', session_uuid: 'su-a', kind: 'agent',
    running_context_used_pct: pct,
});

describe('contextPlan', () => {
    it('steps colour on the foot bar ladder: 25/50/80/95', () => {
        const scale = (p: number) => contextPlan({ name: 'a', running_context_used_pct: p })?.scale;
        expect([10, 25, 50, 80, 95].map(scale)).toEqual([1, 2, 3, 4, 5]);
    });

    it('paints nothing for null, absent or non-numeric, never zero', () => {
        expect(contextPlan({ name: 'a', running_context_used_pct: null })).toBeNull();
        expect(contextPlan({ name: 'a' })).toBeNull();
        expect(contextPlan({ name: 'a', running_context_used_pct: 'x' })).toBeNull();
    });

    it('clamps to 0..100 and speaks a rounded percent', () => {
        expect(contextPlan({ name: 'a', running_context_used_pct: 140 })?.pct).toBe(100);
        expect(contextPlan({ name: 'a', running_context_used_pct: 41.4 })?.label).toContain('41');
    });
});

describe('row context gauge preference and render', () => {
    let container: HTMLElement;
    let component: unknown;
    beforeAll(() => { loadLegacyDrawer(); });
    afterEach(() => {
        if (component) unmount(component as never);
        component = null;
        container?.remove();
        setDrawerEnv(null);
    });

    function render(density: string, r: Record<string, unknown>): HTMLElement {
        container = document.body.appendChild(document.createElement('div'));
        const plan = buildRowPlan(r as never, density, undefined, null, rowHost());
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
        return container;
    }

    it('is on by default at every density, and an explicit off stays off', () => {
        for (const d of ['compact', 'cozy', 'detailed']) expect(defaultFor(d, 'context')).toBe(true);
        setDrawerEnv({});
        for (const d of ['compact', 'cozy', 'detailed']) {
            expect(render(d, row(44)).querySelector('.session-sidebar-row-context'), d).not.toBeNull();
            unmount(component as never); component = null; container.remove();
        }
        setDrawerEnv({ PreferenceBridge: { read: () => ({ cozy: { context: false } }) } });
        expect(render('cozy', row(44)).querySelector('.session-sidebar-row-context')).toBeNull();
    });

    it('draws at all three densities once turned on, filled to the percent', () => {
        setDrawerEnv({ PreferenceBridge: { read: () => ({ compact: { context: true }, cozy: { context: true }, detailed: { context: true } }) } });
        expect(iconVisible('cozy', 'context')).toBe(true);
        for (const d of ['compact', 'cozy', 'detailed']) {
            const el = render(d, row(44));
            const gauge = el.querySelector('.session-sidebar-row-context');
            expect(gauge, d).not.toBeNull();
            expect(gauge?.getAttribute('data-scale')).toBe('2');
            expect((el.querySelector('.oc-gauge__fill') as HTMLElement).style.width).toBe('44%');
            expect(el.querySelector('.session-sidebar-row')?.getAttribute('data-context-gauge')).toBe('1');
            unmount(component as never); component = null; container.remove();
        }
    });

    it('draws nothing when on but the context was not measured', () => {
        setDrawerEnv({ PreferenceBridge: { read: () => ({ cozy: { context: true } }) } });
        const el = render('cozy', row(null));
        expect(el.querySelector('.session-sidebar-row-context')).toBeNull();
        expect(el.querySelector('.session-sidebar-row')?.hasAttribute('data-context-gauge')).toBe(false);
    });
});
