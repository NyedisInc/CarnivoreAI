/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { bandEvents } from './row-events';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const SUN = '.session-sidebar-row-wake-sun';
const LED = '.status-led';

function fireShift(down: boolean): void {
    window.dispatchEvent(new KeyboardEvent(down ? 'keydown' : 'keyup', { shiftKey: down }));
    flushSync();
}

describe('the retired Shift-held wake sun', () => {
    let container: HTMLElement;
    let cleanupBand: (() => void) | void;
    let component: unknown;
    let runWake: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        container = document.body.appendChild(document.createElement('div'));
        runWake = vi.fn().mockResolvedValue(false);
        (globalThis as Record<string, unknown>).SessionRowMenuSleep = { runWake };
        (globalThis as Record<string, unknown>).NavigationGeneration = {
            begin: (t: string) => t,
            isCurrent: () => true,
            keep: () => true,
        };
        const ctrl = { _rows: [{ name: 'cloude_z', asleep: true, session_uuid: 'uuid-z', label: 'zzz' }] };
        (globalThis as Record<string, unknown>).SessionSidebar = ctrl;
        cleanupBand = bandEvents()(container);

        const plan = buildRowPlan(
            { name: 'cloude_z', status: 'asleep', asleep: true, session_uuid: 'uuid-z', label: 'zzz' },
            'compact', undefined, null, {} as RowHost,
        );
        component = mount(SessionRow, { target: container, props: { p: plan as never } });
        flushSync();
    });

    afterEach(() => {
        fireShift(false);
        if (typeof cleanupBand === 'function') cleanupBand();
        unmount(component as never);
        container.remove();
        delete (globalThis as Record<string, unknown>).SessionRowMenuSleep;
        delete (globalThis as Record<string, unknown>).NavigationGeneration;
        delete (globalThis as Record<string, unknown>).SessionSidebar;
    });

    it('Shift held over an asleep row keeps the moon and draws no sun', () => {
        fireShift(true);
        expect(container.querySelector(SUN)).toBeNull();
        expect(container.querySelector('[data-wake-sun-session]')).toBeNull();
        expect(container.querySelector(`${LED}[data-inner="asleep"]`)).not.toBeNull();
    });

    it('a Shift-click on the asleep row does not wake it', async () => {
        fireShift(true);
        container.querySelector<HTMLElement>('.session-sidebar-row-main')?.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
        await Promise.resolve();
        await Promise.resolve();
        expect(runWake).not.toHaveBeenCalled();
    });
});
