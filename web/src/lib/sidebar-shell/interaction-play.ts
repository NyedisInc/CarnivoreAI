import { expect } from 'vitest';
import { closeItemMenu } from '../item-menu/open.svelte';
import { canonicalDom } from './legacy-fixture';
import { legacyAnswer, suiteOfTest } from './goldens';
import type { LegacyWindow } from './legacy-fixture';
import { loadInteractions, recorded, settle, startRun, type Harness, type RunOptions } from './interaction-fixture';
import { SHELL_ATTR, sidebarShell } from './shell.svelte';

export type { Harness, RunOptions };
export { recorded, settle };

export interface Snapshot {
    label: string;
    list: string;
    menu: string | null;
    focus: string;
    collapsed: string[];
    groups: string;
}

export type Steps = (h: Harness, g: Gestures) => Promise<void>;

export interface Gestures {
    click(selector: string): Promise<void>;
    key(key: string, target?: Element | null): Promise<void>;
    pick(label: string): Promise<void>;
    type(value: string): Promise<void>;
    snap(label: string): void;
    el(selector: string): Element;
}

let w: LegacyWindow;

export function loadShell(): LegacyWindow {
    w = loadInteractions(sidebarShell);
    return w;
}

function focusOf(): string {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return 'body';
    if (el.closest('.acm-menu') && el.dataset['node']) return `item:${el.querySelector('.acm-label')?.textContent ?? ''}`;
    return [el.tagName, el.className, el.getAttribute('data-menu-index'), el.getAttribute('data-group-toggle')].join('|');
}

export function menuItems(): HTMLElement[] {
    return Array.from(document.querySelectorAll<HTMLElement>('.acm-menu[data-level="0"] [data-node]'));
}

export interface Run {
    snaps: Snapshot[];
    events: unknown[];
    shell: string | null;
}

export async function play(steps: Steps, o: RunOptions = {}): Promise<Run> {
    const mode = 'shell';
    const h = startRun(o);
    const shell = h.list.getAttribute(SHELL_ATTR);
    const snaps: Snapshot[] = [];
    const el = (selector: string): Element => {
        const found = document.querySelector(selector);
        if (!found) throw new Error(`${mode}: nothing matches ${selector}`);
        return found;
    };
    const g: Gestures = {
        el,
        async click(selector) {
            el(selector).dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, cancelable: true }));
            (el(selector) as HTMLElement).click();
            await settle();
        },
        async key(key, target) {
            const at = target || document.activeElement || document.body;
            at.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
            await settle();
        },
        async pick(label) {
            const everyLevel = (): HTMLElement[] => Array.from(document.querySelectorAll<HTMLElement>('.acm-menu [data-node]'));
            const byLabel = (): HTMLElement | undefined => everyLevel().find((b) => b.querySelector('.acm-label')?.textContent === label);
            if (!byLabel()) {
                everyLevel().find((b) => b.querySelector('.acm-label')?.textContent === 'customize')?.click();
                await settle();
            }
            const item = byLabel();
            if (!item) throw new Error(`${mode}: no menu item ${label}`);
            item.click();
            await settle();
        },
        async type(value) {
            const input = el('#session-sidebar-list .session-sidebar-rename-input') as HTMLInputElement;
            input.value = value;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            await settle();
        },
        snap(label) {
            const menu = document.querySelector('.acm-menu');
            const state = w.SessionSidebarArrangement.current();
            snaps.push({
                label,
                list: canonicalDom(h.list),
                menu: menu ? menuItems().map((b) => `${b.querySelector('.acm-label')?.textContent ?? ''}${b.getAttribute('aria-disabled') ? ` (${b.getAttribute('data-tooltip') ?? 'inert'})` : ''}`).join('|') : null,
                focus: focusOf(),
                collapsed: (state.collapsed || []).slice(),
                groups: JSON.stringify(h.groups()),
            });
        },
    };
    await steps(h, g);
    g.snap('end');
    closeItemMenu();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    const input = document.querySelector('#session-sidebar-list .session-sidebar-rename-input') as HTMLInputElement | null;
    if (input) input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    return { snaps, events: recorded().slice(), shell };
}

export function legacyRun(run: Run): Run {
    return legacyAnswer(suiteOfTest(), { ...run, shell: null });
}

export async function same(steps: Steps, o: RunOptions = {}): Promise<Run> {
    const svelte = await play(steps, o);
    const legacy = legacyRun(svelte);
    expect(legacy.shell).toBeNull();
    expect(svelte.shell).toBe('svelte');
    expect(svelte.events).toEqual(legacy.events);
    const around = (snaps: Snapshot[]) => snaps.map(({ menu, focus, ...rest }) => ({ ...rest, menu: menu === null, focus: focus.startsWith('item:') || focus.includes('session-sidebar-group-menu__item') ? 'menu' : focus }));
    expect(around(svelte.snaps)).toEqual(around(legacy.snaps));
    return svelte;
}

export const TOGGLE = (key: string): string => `#session-sidebar-list [data-group-toggle="${key}"]`;

