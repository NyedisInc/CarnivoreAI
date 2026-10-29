/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import { openSessionAutomationsFor } from './row-controls';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const ROW = { name: 'cloude_a', status: 'idle', agent_family: 'claude', session_id: 'ses_1', session_uuid: 'uuid-1' };
const SERVER = { automations_state: 'ok', automations_total: 2, automations_enabled: 1 };
let container: HTMLElement | null = null;
let component: unknown;

function renderRow(stored: unknown, extra: Record<string, unknown> = SERVER, mode: 'compact' | 'cozy' | 'detailed' = 'compact'): HTMLElement {
    setDrawerEnv({ PreferenceBridge: { read: () => stored } });
    container = document.body.appendChild(document.createElement('div'));
    const plan = buildRowPlan({ ...ROW, ...extra } as never, mode, undefined, null, {} as RowHost);
    component = mount(SessionRow, { target: container, props: { p: plan as never } });
    flushSync();
    return container;
}

const iconOf = (el: HTMLElement): HTMLElement | null => el.querySelector('.session-sidebar-row-automations-icon');

afterEach(() => {
    setDrawerEnv(null);
    if (component) unmount(component as never);
    container?.remove();
    container = null;
    component = null;
    vi.unstubAllGlobals();
});

describe('the carnivore timers row icon', () => {
    it('draws by default on a session the server says has timers, as a button that says these are carnivore timers', () => {
        const icon = iconOf(renderRow(null))!;
        expect(icon).not.toBeNull();
        expect(icon.tagName).toBe('BUTTON');
        expect(icon.getAttribute('title')).toContain('carnivore timers: 2 scheduled for this session, 1 on');
        expect(icon.getAttribute('data-automations-session-uuid')).toBe('uuid-1');
    });

    it('is hidden when the preference says so', () => {
        expect(iconOf(renderRow({ compact: { automations: false } }))).toBeNull();
    });

    it.each([
        ['ok', 'every timer ran fine'],
        ['warning', 'skipped, canceled or is waiting on you'],
        ['error', 'a timer failed'],
        ['disabled', 'all timers are switched off'],
    ])('state %s sets data-state and says it in words, to a screen reader too', (state, words) => {
        const icon = iconOf(renderRow(null, { ...SERVER, automations_state: state }))!;
        expect(icon.getAttribute('data-state')).toBe(state);
        expect(icon.classList.contains('oc-timer-state')).toBe(true);
        expect(icon.querySelector('.oc-timer-glyph')).not.toBeNull();
        expect(icon.getAttribute('title')).toContain(words);
        expect(icon.getAttribute('aria-label')).toContain(words);
    });

    it('draws at cozy and detailed too, where the body carries the live counts', () => {
        for (const mode of ['cozy', 'detailed'] as const) {
            const el = renderRow({ [mode]: { automations: true } }, SERVER, mode);
            expect(iconOf(el), mode).not.toBeNull();
            unmount(component as never);
            component = null;
            el.remove();
        }
    });

    it('draws nothing for a session with no automation (none) or one the server has not measured (null or absent)', () => {
        for (const extra of [{ automations_state: 'none', automations_total: 0, automations_enabled: 0 }, { automations_state: null }, {}]) {
            const el = renderRow(null, extra);
            expect(iconOf(el), JSON.stringify(extra)).toBeNull();
            unmount(component as never);
            component = null;
            el.remove();
        }
    });

    it('lists each scheduled thing by name and next fire time under the count, off ones as off, and says how many more the cap left out', () => {
        const next = [
            { name: 'sweep the todos', enabled: true, next_fire_at: Date.UTC(2026, 9, 12, 15, 0, 0) / 1000 },
            { name: 'parked check', enabled: false, next_fire_at: null },
        ];
        const lines = String(iconOf(renderRow(null, { ...SERVER, automations_next: next }))!.getAttribute('title')).split('\n');
        expect(lines[0]).toContain('carnivore timers: 2 scheduled for this session, 1 on');
        expect(lines[1]).toMatch(/^sweep the todos, next /);
        expect(lines[2]).toBe('parked check, off');
        expect(lines).toHaveLength(3);
        const capped = String(iconOf(renderRow(null, { ...SERVER, automations_total: 7, automations_next: next }))!.getAttribute('title')).split('\n');
        expect(capped.at(-1)).toBe('+5 more');
        expect(String(iconOf(renderRow(null))!.getAttribute('title'))).not.toContain('\n');
    });

    it('a click opens the automations page at that session', () => {
        const opened: string[] = [];
        vi.stubGlobal('CloudeWeb', { openAutomationsScreen: () => { opened.push(location.hash); return true; } });
        openSessionAutomationsFor(iconOf(renderRow(null))!);
        expect(opened).toEqual(['#automations/session/uuid-1']);
    });
});

describe('an asleep row (issues #1903, #2688)', () => {
    const ASLEEP = { asleep: true, status: 'asleep', agent_family: 'claude', session_id: null };

    it('draws no alarm: its one clock is the wake clock, which opens the automations (row-one-clock.test.ts)', () => {
        expect(iconOf(renderRow(null, { ...ASLEEP, ...SERVER }))).toBeNull();
    });
});
