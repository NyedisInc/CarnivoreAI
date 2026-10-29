/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { activateRow, armAsleepRow } from './row-activate';
import { bandEvents } from './row-events';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';
import { resetWakeArm, wakeArm } from './wake-arm.svelte';

const OVERLAY = '.session-sidebar-row-wake-arm';
const GO = '[data-wake-arm-go]';
const X = '[data-wake-arm-cancel]';
const g = globalThis as Record<string, unknown>;

let panel: HTMLElement;
let container: HTMLElement;
let cleanupBand: (() => void) | void;
let apps: unknown[] = [];
let runWake: ReturnType<typeof vi.fn>;

function drawRow(name: string, over: Record<string, unknown> = {}): HTMLElement {
    const host = document.createElement('div');
    container.appendChild(host);
    const plan = buildRowPlan(
        { name, status: 'asleep', asleep: true, session_uuid: `uuid-${name}`, label: `label ${name}`, ...over },
        'cozy', 'p:1', null, {} as RowHost,
    );
    apps.push(mount(SessionRow, { target: host, props: { p: plan as never } }));
    flushSync();
    return host.querySelector('.session-sidebar-row') as HTMLElement;
}

const rowOf = (name: string): HTMLElement => container.querySelector(`.session-sidebar-row[data-name="${name}"]`) as HTMLElement;

function pastGrace(): void {
    vi.advanceTimersByTime(400);
}

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    if (!(globalThis as { CSS?: { escape?: unknown } }).CSS?.escape) {
        g.CSS = { escape: (v: string) => String(v).replace(/["\\\]\[]/g, '\\$&') };
    }
    panel = document.body.appendChild(document.createElement('div'));
    panel.className = 'session-sidebar-panel session-sidebar-panel--open';
    const list = panel.appendChild(document.createElement('div'));
    list.id = 'session-sidebar-list';
    container = list.appendChild(document.createElement('div'));
    runWake = vi.fn().mockResolvedValue(false);
    g.SessionRowMenuSleep = { runWake };
    g.NavigationGeneration = { begin: (t: string) => t, isCurrent: () => true, keep: () => true };
    g.SessionSidebar = {
        _rows: [
            { name: 'cloude_a', asleep: true, session_uuid: 'uuid-cloude_a', label: 'label cloude_a' },
            { name: 'cloude_b', asleep: true, session_uuid: 'uuid-cloude_b', label: 'label cloude_b' },
        ],
    };
    cleanupBand = bandEvents()(container);
});

afterEach(() => {
    resetWakeArm();
    if (typeof cleanupBand === 'function') cleanupBand();
    for (const a of apps) unmount(a as never);
    apps = [];
    panel.remove();
    for (const k of ['SessionRowMenuSleep', 'PreferenceBridge', 'NavigationGeneration', 'SessionSidebar']) delete g[k];
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe('the armed wake of an asleep row', () => {
    it('a click arms the row: wake and X draw inside it, nothing wakes, the content is inert', () => {
        const el = drawRow('cloude_a');
        expect(el.querySelector(OVERLAY)).toBeNull();
        el.click();
        flushSync();
        const overlay = el.querySelector(OVERLAY);
        expect(overlay).not.toBeNull();
        expect(el.hasAttribute('data-wake-armed')).toBe(true);
        expect(el.querySelector(GO)?.textContent).toBe('wake');
        const shown = el.querySelector('[data-row-name]')!.textContent;
        expect(el.querySelector(GO)?.getAttribute('aria-label')).toBe(`wake ${shown}`);
        expect(el.querySelector(X)).not.toBeNull();
        expect(el.querySelector('.session-sidebar-row-main')?.hasAttribute('inert')).toBe(true);
        expect(runWake).not.toHaveBeenCalled();
        const css = readFileSync('../client/css/session-sidebar-rows.css', 'utf8');
        const rule = css.slice(css.indexOf('.session-sidebar-row-wake-arm {'));
        expect(rule.slice(0, rule.indexOf('}'))).toMatch(/position: absolute;[\s\S]*inset: 0;/);
    });

    it('the X and Escape disarm, and the document listeners go with them', () => {
        const add = vi.spyOn(document, 'addEventListener');
        const remove = vi.spyOn(document, 'removeEventListener');
        const el = drawRow('cloude_a');
        el.click();
        flushSync();
        expect(add.mock.calls.map((c) => c[0])).toEqual(expect.arrayContaining(['keydown', 'pointerdown']));
        el.querySelector<HTMLElement>(X)!.click();
        flushSync();
        expect(el.querySelector(OVERLAY)).toBeNull();
        expect(remove.mock.calls.map((c) => c[0])).toEqual(expect.arrayContaining(['keydown', 'pointerdown']));
        expect(runWake).not.toHaveBeenCalled();

        el.click();
        flushSync();
        expect(el.querySelector(OVERLAY)).not.toBeNull();
        const esc = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
        document.dispatchEvent(esc);
        flushSync();
        expect(esc.defaultPrevented).toBe(true);
        expect(el.querySelector(OVERLAY)).toBeNull();
        expect(wakeArm.key).toBe('');
    });

    it('a pointerdown outside the row disarms it; one inside does not', () => {
        const el = drawRow('cloude_a');
        el.click();
        flushSync();
        el.querySelector(OVERLAY)!.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        flushSync();
        expect(el.querySelector(OVERLAY)).not.toBeNull();
        document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        flushSync();
        expect(el.querySelector(OVERLAY)).toBeNull();
    });

    it('wake runs the existing wake once, even pressed twice, and reads waking while it runs', async () => {
        let done: (v: boolean) => void = () => {};
        runWake.mockReturnValue(new Promise<boolean>((r) => { done = r; }));
        const el = drawRow('cloude_a');
        el.click();
        flushSync();
        pastGrace();
        const go = el.querySelector<HTMLElement>(GO)!;
        go.click();
        go.click();
        flushSync();
        expect(runWake).toHaveBeenCalledTimes(1);
        expect(runWake).toHaveBeenCalledWith({ name: 'cloude_a', label: 'label cloude_a', sessionUuid: 'uuid-cloude_a', surface: 'sidebar' });
        expect(go.getAttribute('aria-disabled')).toBe('true');
        expect(go.textContent).toBe('waking');
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
        document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }));
        flushSync();
        expect(el.querySelector(OVERLAY)).not.toBeNull();
        done(false);
        await vi.waitFor(() => expect(el.querySelector(OVERLAY)).toBeNull());
        expect(runWake).toHaveBeenCalledTimes(1);
    });

    it('arming a second row disarms the first', () => {
        const a = drawRow('cloude_a');
        const b = drawRow('cloude_b');
        a.click();
        flushSync();
        expect(a.querySelector(OVERLAY)).not.toBeNull();
        b.click();
        flushSync();
        expect(a.querySelector(OVERLAY)).toBeNull();
        expect(b.querySelector(OVERLAY)).not.toBeNull();
    });

    it('NEGATIVE: the Space that armed the row cannot also wake it', () => {
        const el = drawRow('cloude_a');
        el.focus();
        el.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }));
        flushSync();
        const go = el.querySelector<HTMLElement>(GO);
        expect(go).not.toBeNull();
        go!.click();
        expect(runWake).not.toHaveBeenCalled();
        pastGrace();
        go!.click();
        expect(runWake).toHaveBeenCalledTimes(1);
    });

    it('NEGATIVE: a live row, a row outside the open drawer and a detached stand-in row never arm', async () => {
        const live = drawRow('cloude_live', { status: 'idle', asleep: false });
        expect(armAsleepRow(live)).toBe(false);
        expect(live.querySelector(OVERLAY)).toBeNull();

        const asleep = drawRow('cloude_a');
        panel.classList.remove('session-sidebar-panel--open');
        expect(armAsleepRow(asleep)).toBe(false);
        panel.classList.add('session-sidebar-panel--open');

        const detached = document.createElement('div');
        detached.className = 'session-sidebar-row';
        detached.dataset.name = 'cloude_a';
        detached.dataset.asleep = '1';
        await activateRow(g.SessionSidebar as never, detached);
        expect(wakeArm.key).toBe('');
        expect(runWake).not.toHaveBeenCalled();
        expect(asleep.querySelector(OVERLAY)).toBeNull();
    });

    it('busy: with a wake in flight a click on another asleep row does not arm, announce or swallow the click', async () => {
        let done: (v: boolean) => void = () => {};
        runWake.mockReturnValue(new Promise<boolean>((r) => { done = r; }));
        const live = document.createElement('div');
        live.id = 'session-sidebar-live';
        document.body.appendChild(live);
        const a = drawRow('cloude_a');
        const b = drawRow('cloude_b');
        a.click();
        flushSync();
        pastGrace();
        a.querySelector<HTMLElement>(GO)!.click();
        flushSync();
        expect(wakeArm.busy).toBe(true);
        live.textContent = '';
        const before = wakeArm.key;
        expect(armAsleepRow(b)).toBe(false);
        b.click();
        flushSync();
        expect(wakeArm.key).toBe(before);
        expect(b.querySelector(OVERLAY)).toBeNull();
        expect(live.textContent).toBe('');
        done(false);
        await vi.waitFor(() => expect(wakeArm.busy).toBe(false));
        live.remove();
        expect(armAsleepRow(b)).toBe(true);
    });

    it('NEGATIVE: a terminal row (no light) carrying data-asleep never arms, so no click arms in state with nothing drawn', () => {
        const term = drawRow('cloude_term', { agent_family: 'shell' });
        expect(term.dataset.asleep).toBe('1');
        expect(term.querySelector('.status-dot, [data-status]')).toBeNull();
        expect(armAsleepRow(term)).toBe(false);
        term.click();
        flushSync();
        expect(wakeArm.key).toBe('');
        expect(term.querySelector(OVERLAY)).toBeNull();
        const lit = drawRow('cloude_lit');
        expect(armAsleepRow(lit)).toBe(true);
    });

    it('an armed row hides its pin and kebab cluster (layout kept) so the X sits alone', () => {
        const css = readFileSync('../client/css/session-sidebar-rows.css', 'utf8');
        const at = css.indexOf('.session-sidebar-row[data-wake-armed] .session-sidebar-row-controls-cluster {');
        expect(at).toBeGreaterThan(-1);
        const rule = css.slice(at, css.indexOf('}', at));
        expect(rule).toMatch(/visibility: hidden;/);
        expect(rule).not.toMatch(/display:|position:|width:|height:/);

        const el = drawRow('cloude_a');
        expect(el.hasAttribute('data-wake-armed')).toBe(false);
        expect(el.querySelector('.session-sidebar-row-controls-cluster')).not.toBeNull();
        el.click();
        flushSync();
        expect(el.matches('.session-sidebar-row[data-wake-armed]')).toBe(true);
        expect(el.querySelector('.session-sidebar-row[data-wake-armed] .session-sidebar-row-controls-cluster, [data-wake-armed] .session-sidebar-row-controls-cluster')).not.toBeNull();
        expect(el.querySelector(`.session-sidebar-row-controls-cluster ${X}`)).toBeNull();
    });
});
