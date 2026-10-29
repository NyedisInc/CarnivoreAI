import { closeRowMenu } from '../item-menu/row-open';
import { expect } from 'vitest';
import { canonicalDom } from './legacy-fixture';
import { legacyAnswer, suiteOfTest } from './goldens';
import { ROW_PX, rowEvents, settle, startRowRun } from './row-interaction-fixture';
import { SHELL_ATTR } from './shell.svelte';
import { resetWakeArm } from './wake-arm.svelte';

export interface Gestures {
    el(selector: string): HTMLElement;
    has(selector: string): boolean;
    click(selector: string, init?: MouseEventInit): Promise<void>;
    key(selector: string, key: string, init?: KeyboardEventInit): Promise<void>;
    type(text: string): Promise<void>;
    boxKey(key: string): Promise<void>;
    contextmenu(selector: string): Promise<void>;
    press(fromSelector: string): PointerHold;
    drag(fromSelector: string, toRowIndex: number): Promise<void>;
}

export interface PointerHold {
    moveTo(rowIndex: number): void;
    release(): Promise<void>;
}

export type Steps = (g: Gestures) => Promise<void>;

export interface Outcome {
    shell: string | null;
    events: unknown[];
    dom: string;
    arrangement: string;
    focus: string;
    live: string;
    snaps: string[];
}

export const ROW = (name: string): string => `.session-sidebar-row[data-name="${name}"]`;

export const ROW_IN = (band: string, name: string): string =>
    `.session-sidebar-group[data-group="${band}"] .session-sidebar-row[data-name="${name}"]`;

export const BOX = '.session-sidebar-rename-input';

let snaps: string[] = [];

export function snap(): void {
    const list = document.getElementById('session-sidebar-list');
    snaps.push(list ? canonicalDom(list) : '');
}

function pe(type: string, y: number, x = 10): PointerEvent {
    return new PointerEvent(type, {
        bubbles: true, cancelable: true, clientX: x, clientY: y, pointerId: 1, pointerType: 'mouse', button: 0,
    });
}

function gestures(): Gestures {
    const mode = 'shell';
    const el = (selector: string): HTMLElement => {
        const found = document.querySelector(`#session-sidebar-list ${selector}`);
        if (!found) throw new Error(`${mode}: nothing matches ${selector}`);
        return found as HTMLElement;
    };
    const press = (fromSelector: string): PointerHold => {
        const from = el(fromSelector);
        let y = from.getBoundingClientRect().top + 2;
        from.dispatchEvent(pe('pointerdown', y));
        return {
            moveTo(rowIndex: number) {
                const y1 = rowIndex * ROW_PX + ROW_PX - 2;
                while (Math.abs(y1 - y) >= 4) {
                    y += y1 > y ? 4 : -4;
                    document.dispatchEvent(pe('pointermove', y));
                }
                y = y1;
                document.dispatchEvent(pe('pointermove', y));
            },
            async release() {
                document.dispatchEvent(pe('pointerup', y));
                await settle();
            },
        };
    };
    const box = (): HTMLInputElement => {
        const found = document.querySelector(`#session-sidebar-list ${BOX}`);
        if (!found) throw new Error(`${mode}: no rename box is open`);
        return found as HTMLInputElement;
    };
    return {
        el,
        has: (selector) => !!document.querySelector(`#session-sidebar-list ${selector}`),
        async click(selector, init = {}) {
            el(selector).dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...init }));
            await settle();
        },
        async key(selector, key, init = {}) {
            const target = el(selector);
            target.focus();
            target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }));
            await settle();
        },
        async type(text) {
            const input = box();
            input.value = text;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            await settle();
        },
        async boxKey(key) {
            box().dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
            await settle();
        },
        async contextmenu(selector) {
            el(selector).dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }));
            await settle();
        },
        press,
        async drag(fromSelector, toRowIndex) {
            const hold = press(fromSelector);
            hold.moveTo(toRowIndex);
            await hold.release();
        },
    };
}

export async function play(w: Record<string, any>, steps: Steps, groups: unknown[] = []): Promise<Outcome> {
    const { list } = startRowRun(groups);
    snaps = [];
    const shell = list.getAttribute(SHELL_ATTR);
    await steps(gestures());
    const active = document.activeElement as HTMLElement | null;
    const out: Outcome = {
        shell,
        events: rowEvents().slice(),
        dom: canonicalDom(list),
        arrangement: JSON.stringify(w.SessionSidebarArrangement.current()),
        focus: active ? `${active.tagName}|${active.className}|${active.getAttribute('data-name') || ''}` : 'none',
        live: document.getElementById('session-sidebar-live')?.textContent || '',
        snaps: snaps.slice(),
    };
    // Nothing left open for the next run.
    const input = document.querySelector(`#session-sidebar-list ${BOX}`);
    if (input) input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    closeRowMenu();
    (document.activeElement as HTMLElement | null)?.blur?.();
    resetWakeArm();
    await settle();
    return out;
}

export type Differs = 'focus';

export function legacyRun(run: Outcome): Outcome {
    return legacyAnswer(suiteOfTest(), { ...run, shell: null });
}

export async function same(
    w: Record<string, any>, steps: Steps, o: { groups?: unknown[]; differs?: Differs[] } = {},
): Promise<{ legacy: Outcome; svelte: Outcome }> {
    const svelte = await play(w, steps, o.groups);
    const legacy = legacyRun(svelte);
    expect(legacy.shell).toBeNull();
    expect(svelte.shell).toBe('svelte');
    expect(svelte.events).toEqual(legacy.events);
    expect(svelte.snaps).toEqual(legacy.snaps);
    expect(svelte.dom).toBe(legacy.dom);
    expect(svelte.arrangement).toBe(legacy.arrangement);
    expect(svelte.live).toBe(legacy.live);
    if (!(o.differs || []).includes('focus')) expect(svelte.focus).toBe(legacy.focus);
    return { legacy, svelte };
}

export function names(run: Outcome): string[] {
    return run.events.map((e) => String((e as unknown[])[0]));
}
