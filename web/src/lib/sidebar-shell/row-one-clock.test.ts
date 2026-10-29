/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import { openSessionAutomationsFor } from './row-controls';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const ASLEEP = {
    name: 'cloude_a', asleep: true, status: 'asleep', agent_family: 'claude', session_id: null, session_uuid: 'uuid-1',
    automations_state: 'ok', automations_total: 2, automations_enabled: 1,
};
let container: HTMLElement | null = null;
let component: unknown;

function render(extra: Record<string, unknown>): HTMLElement {
    setDrawerEnv({ PreferenceBridge: { read: () => null } });
    container = document.body.appendChild(document.createElement('div'));
    const plan = buildRowPlan({ ...ASLEEP, ...extra } as never, 'compact', undefined, null, {} as RowHost);
    component = mount(SessionRow, { target: container, props: { p: plan as never } });
    flushSync();
    return container;
}

afterEach(() => {
    setDrawerEnv(null);
    if (component) unmount(component as never);
    container?.remove();
    container = null;
    component = null;
    vi.unstubAllGlobals();
});

describe('a sleeping row shows one clock', () => {
    it('draws the grey wake clock and no green timers alarm when a wake is scheduled', () => {
        const el = render({ next_wake_at: 1.8e9 });
        expect(el.querySelector('.session-sidebar-row-automations-icon')).toBeNull();
        expect(el.querySelectorAll('.session-sidebar-row-wake-icon')).toHaveLength(1);
    });

    it('draws no clock at all when nothing will wake it', () => {
        const el = render({ next_wake_at: null });
        expect(el.querySelector('.session-sidebar-row-automations-icon')).toBeNull();
        expect(el.querySelector('.session-sidebar-row-wake-icon')).toBeNull();
    });

    it('a click on the wake clock opens the automations page at that session', () => {
        const opened: string[] = [];
        vi.stubGlobal('CloudeWeb', { openAutomationsScreen: () => { opened.push(location.hash); return true; } });
        const wake = render({ next_wake_at: 1.8e9 }).querySelector('.session-sidebar-row-wake-icon')!;
        expect(wake.tagName).toBe('BUTTON');
        openSessionAutomationsFor(wake);
        expect(opened).toEqual(['#automations/session/uuid-1']);
    });

    it('a live row keeps its timers alarm', () => {
        const el = render({ asleep: false, status: 'idle', session_id: 'ses_1' });
        expect(el.querySelector('.session-sidebar-row-automations-icon')).not.toBeNull();
    });
});
