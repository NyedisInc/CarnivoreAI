/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { setLocale } from '../i18n/index.svelte';
import { DEFAULT_WIDTH_PX } from '../drawer/resize';
import type { RowHost } from '../sidebar-shell/row-host';
import MotionPanel from './MotionPanel.svelte';
import RowIconsPanel from './RowIconsPanel.svelte';
import SwitchControl from './controls/SwitchControl.svelte';
import { ROW_DENSITIES, ROW_ICON_KINDS, rowIcons } from './row-icons-store.svelte';
import { SETTINGS, settingById, type GroupId } from './settings-registry';
import { animationsState } from '../motion/animations-state.svelte';

setLocale('en');

const g = globalThis as { PreferenceBridge?: unknown };
const mounted: Record<string, unknown>[] = [];
let stored: Record<string, unknown> = {};

function stubBridge(): void {
    g.PreferenceBridge = {
        read: (field: string, local: () => unknown) => (field in stored ? stored[field] : local()),
        write: (field: string, value: unknown) => { stored[field] = value; return Promise.resolve({ status: 'committed' }); },
        follow: () => () => {},
    };
}

beforeEach(() => {
    stored = {};
    stubBridge();
    rowIcons.value = {};
    animationsState.on = true;
});

afterEach(() => {
    for (const m of mounted.splice(0)) void unmount(m);
    document.body.replaceChildren();
    delete g.PreferenceBridge;
    rowIcons.value = {};
});

function draw(component: unknown, props: Record<string, unknown>): HTMLElement {
    const target = document.body.appendChild(document.createElement('div'));
    mounted.push(mount(component as never, { target, props }) as Record<string, unknown>);
    flushSync();
    return target;
}

const HOST = {
    actions: { offersMenu: () => true, specs: () => [] },
    menu: { contextFromRow: () => ({}), triggerSpec: () => ({ attrs: { class: 'session-row-menu-trigger', type: 'button' }, svg: '' }) },
} as unknown as RowHost;

const toggle = (root: HTMLElement, density: string, kind: string): HTMLInputElement =>
    root.querySelector<HTMLInputElement>(`.rip__dens[data-density="${density}"] input[type="checkbox"][aria-label="${kind} icon at ${density} density"]`)!;

async function settle(): Promise<void> {
    for (let i = 0; i < 5; i += 1) await new Promise((r) => setTimeout(r, 0));
    flushSync();
}

describe('agent rows', () => {
    test('each row size lists exactly the eight icons a drawer row lets you toggle, labelled', () => {
        const root = draw(RowIconsPanel, { host: HOST });
        expect(ROW_ICON_KINDS).toEqual(['agents', 'shells', 'timers', 'cup', 'pin', 'menu', 'context', 'automations']);
        for (const density of ROW_DENSITIES) {
            const labels = [...root.querySelectorAll(`.rip__dens[data-density="${density}"] input[type="checkbox"]`)].map((el) => el.getAttribute('aria-label'));
            expect(labels, density).toEqual(['agents', 'shells', 'timers', 'keep awake', 'pin', 'menu', 'context gauge', 'carnivore timers'].map((k) => `${k} icon at ${density} density`));
        }
    });

    test('the previews are the drawer\'s real row at the drawer\'s default width, one per row size', () => {
        const root = draw(RowIconsPanel, { host: HOST });
        for (const density of ROW_DENSITIES) {
            const panel = root.querySelector<HTMLElement>(`.rip__dens[data-density="${density}"] .rip__panel`)!;
            expect(panel.classList.contains('session-sidebar-panel')).toBe(true);
            expect(panel.getAttribute('data-density')).toBe(density);
            expect(panel.style.getPropertyValue('--rip-w')).toBe(`${DEFAULT_WIDTH_PX}px`);
            expect(panel.querySelectorAll('.session-sidebar-row').length).toBe(1);
        }
        expect(root.querySelector('.rip__dens[data-density="compact"] .session-sidebar-row')!.hasAttribute('data-row-body')).toBe(false);
        expect(root.querySelector('.rip__dens[data-density="cozy"] .session-sidebar-row')!.getAttribute('data-row-body')).toBe('cozy');
        expect(root.querySelector('.rip__dens[data-density="detailed"] .session-sidebar-row')!.getAttribute('data-row-body')).toBe('detailed');
    });

    test('a toggle redraws the real row: agents at compact, pin, keep awake cup and the context gauge', () => {
        const root = draw(RowIconsPanel, { host: HOST });
        const compact = (sel: string) => root.querySelector(`.rip__dens[data-density="compact"] ${sel}`);
        expect(compact('.session-sidebar-row-agents-icon')).toBeNull();
        toggle(root, 'compact', 'agents').click();
        flushSync();
        expect(compact('.session-sidebar-row-agents-icon')).not.toBeNull();

        expect(compact('.session-sidebar-row-keep-awake')).not.toBeNull();
        toggle(root, 'compact', 'keep awake').click();
        flushSync();
        expect(compact('.session-sidebar-row-keep-awake')).toBeNull();

        expect(compact('.session-sidebar-row-pin')).not.toBeNull();
        toggle(root, 'compact', 'pin').click();
        flushSync();
        expect(compact('.session-sidebar-row-pin')).toBeNull();

        const cozy = () => root.querySelector('.rip__dens[data-density="cozy"] .session-sidebar-row-context');
        expect(cozy()).not.toBeNull();
        toggle(root, 'cozy', 'context gauge').click();
        flushSync();
        expect(cozy()).toBeNull();
    });

    test('the carnivore timers (session automations) icon is on by default at every size (#1639) and is a labelled check at each', () => {
        const root = draw(RowIconsPanel, { host: HOST });
        for (const density of ROW_DENSITIES) {
            const check = toggle(root, density, 'carnivore timers');
            expect(check, density).not.toBeNull();
            expect(check.checked, density).toBe(true);
        }
        toggle(root, 'detailed', 'carnivore timers').click();
        flushSync();
        expect(toggle(root, 'detailed', 'carnivore timers').checked).toBe(false);
        expect(toggle(root, 'compact', 'carnivore timers').checked).toBe(true);
    });
});

describe('removed settings', () => {
    test('there is no sidebar tabs colour tab, setting or group, and no wake-on-click setting', () => {
        const ids = SETTINGS.map((s) => s.id);
        expect(ids).not.toContain('sidebar_tab_colors');
        expect(ids).not.toContain('wake_on_click');
        const groups = new Set(SETTINGS.map((s) => s.group as GroupId));
        expect([...groups].filter((x) => x.startsWith('appearance.'))).toEqual([
            'appearance.colors', 'appearance.sidebar', 'appearance.status_bar', 'appearance.control_center', 'appearance.motion',
        ]);
    });
});

describe('motion', () => {
    test('the example plays while animations are on, holds still when the switch turns them off, and plays again', async () => {
        const def = settingById('animations')!;
        const root = draw(MotionPanel, { def, t: (k: string) => k });
        const example = root.querySelector<HTMLElement>('.mp__example')!;
        const demo = root.querySelector<HTMLElement>('.mp__demo')!;
        const sw = root.querySelector<HTMLElement>('button.oc-check[role="switch"]')!;
        expect(example.dataset.state).toBe('on');
        expect(demo.classList.contains('mp__demo--still')).toBe(false);

        sw.click();
        await settle();
        expect(stored.animations).toBe(false);
        expect(example.dataset.state).toBe('off');
        expect(demo.classList.contains('mp__demo--still')).toBe(true);
        expect(root.querySelector('[role="status"]')!.textContent).toContain('settings.motion.example.off');

        sw.click();
        await settle();
        expect(example.dataset.state).toBe('on');
        expect(demo.classList.contains('mp__demo--still')).toBe(false);
    });

    test('it explains what stops and why you would turn it off', () => {
        const root = draw(MotionPanel, { def: settingById('animations')!, t: (k: string) => k });
        const keys = root.textContent ?? '';
        for (const key of ['stops.title', 'stops.body', 'why.title', 'why.gpu', 'why.distraction', 'why.sensitivity', 'why.sharing']) {
            expect(keys).toContain(`settings.motion.${key}`);
        }
    });
});

describe('sleep defaults', () => {
    test('"unread sessions stay awake" reads off before the server has answered', () => {
        const root = draw(SwitchControl, { def: settingById('auto_sleep_unread_blocks')!, t: (k: string) => k });
        expect(root.querySelector('button.oc-check[role="switch"]')!.getAttribute('aria-checked')).toBe('false');
    });
});
