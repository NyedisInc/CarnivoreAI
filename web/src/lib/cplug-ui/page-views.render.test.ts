/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { CplugRow } from '../plugins-page/cplugs-adapter';

vi.mock('./api', () => ({
    fetchViewTicket: vi.fn(async () => ({ path: '/cplugs/flowx/view/flow/t/index.html' })),
    callViewRoute: vi.fn(),
}));

import { activeFlyout, closeFlyout } from '../sidebar-widgets/flyout.svelte';
import { flyout, press, rail, railOn, setupRail, settle, teardownRail } from '../sidebar-widgets/fixtures/rail-harness';
import { registerSwarmFlyout } from '../../cplugs/huddle/swarm-flyout';

// The swarm slide-out is the Task Manager plugin's, so the test registers it; the harness no longer does.
registerSwarmFlyout();
import { tabRegistry } from '../dynamic-tabs/registry';
import { tabFlyoutId } from '../sidebar-widgets/tab-flyouts';
import { pageEntries, setPages } from './page-views.svelte';

const KEY = tabFlyoutId('cplug-flowx');
const row = (over: Partial<CplugRow> = {}): CplugRow => ({
    id: 'flowx', runtime: 'sidecar', enabled: true, state: 'active', name: 'Flow <b>X</b>', install_key: 'k1', unverified: true, icon: 'activity',
    page: { menu: 'flow', main: 'flow' }, views: [{ name: 'flow', surfaces: ['panel'] }], ...over,
} as unknown as CplugRow);
const keyOnRail = (): Element | null => rail().querySelector(`[data-rail-widget="${KEY}"]`);
const frames = (root: ParentNode): HTMLIFrameElement[] => Array.from(root.querySelectorAll('iframe'));

beforeEach(async () => { await setupRail(); });
afterEach(async () => { setPages([]); await teardownRail(); });

describe('which rows get a page', () => {
    test('a page needs two views that declare panel, a plugin that is on and active, and the sidecar runtime', () => {
        expect(pageEntries([row()]).map((e) => e.tabId)).toEqual(['cplug-flowx']);
        expect(pageEntries([row({ page: { menu: 'flow', main: 'nope' } })])).toEqual([]);
        expect(pageEntries([row({ views: [{ name: 'flow', surfaces: ['overlay'] }] })])).toEqual([]);
        expect(pageEntries([row({ enabled: false }), row({ state: 'stopped' }), row({ page: null }), row({ runtime: 'compiled' } as never)])).toEqual([]);
    });

    test('the icon is the plugin\'s own unless it is a core rail key; the title leads with the mark and is the literal name', () => {
        expect(pageEntries([row()])[0]?.icon).toBe('activity');
        expect(pageEntries([row({ icon: 'agents' })])[0]?.icon).toBe('plug');
        expect(pageEntries([row({ icon: 'not-a-key' })])[0]?.icon).toBe('plug');
        expect(pageEntries([row()])[0]?.title).toBe('unverified: Flow <b>X</b>');
        expect(pageEntries([row({ unverified: false })])[0]?.title).toBe('third-party: Flow <b>X</b>');
    });
});

describe('the rail key, the slide-out and the page', () => {
    test('the key is drawn while the plugin is on; opening mounts a menu frame and a page frame, both sandboxed; closing removes both; off removes the key', async () => {
        await railOn();
        expect(keyOnRail(), 'nothing offered yet').toBeNull();
        setPages([row()]);
        await settle();
        const key = keyOnRail();
        expect(key, 'the plugin is on: the key is drawn').not.toBeNull();
        expect(key!.getAttribute('aria-label')).toBe('unverified: Flow <b>X</b>');
        expect(tabRegistry.get('cplug-flowx')!.order).toBeGreaterThanOrEqual(900);

        await press(KEY);
        await settle();
        expect(activeFlyout()).toBe(KEY);
        const menu = frames(flyout());
        const page = frames(document.getElementById('plugin-main-view')!);
        expect(menu.map((f) => f.dataset.cplugRole)).toEqual(['menu']);
        expect(page.map((f) => f.dataset.cplugRole)).toEqual(['page']);
        for (const frame of [...menu, ...page]) {
            expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
            expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin');
        }
        expect(document.querySelector('[data-cplug-name]')?.textContent).toBe('Flow <b>X</b>');
        expect(document.querySelector('[data-cplug-box] b')).toBeNull();

        closeFlyout();
        await settle();
        expect(frames(document.getElementById('plugin-main-view')!), 'the page comes down at once').toEqual([]);
        await new Promise((r) => setTimeout(r, 250));
        await settle();
        expect(frames(flyout())).toEqual([]);

        await press(KEY);
        await settle();
        expect(frames(document.getElementById('plugin-main-view')!)).toHaveLength(1);
        setPages([row({ enabled: false })]);
        await settle();
        expect(keyOnRail(), 'the plugin went off: the key goes').toBeNull();
        expect(activeFlyout(), 'and the open slide-out closes with it').toBeNull();
        expect(frames(document.getElementById('plugin-main-view')!)).toEqual([]);
    });
});

describe('the phone', () => {
    test('a hidden step really takes no room: the stylesheet beats the step\'s display:flex for [hidden]', () => {
        const css = readFileSync(join(process.cwd(), 'src', 'lib', 'cplug-ui', 'cplug-ui.css'), 'utf8');
        expect(css).toMatch(/\.cu-page__step\[hidden\]\s*\{[^}]*display:\s*none/);
    });

    test('both frames sit in the slide-out, one visible at a time behind the host-drawn menu | view switch, and no main view is mounted', async () => {
        const width = window.innerWidth;
        Object.defineProperty(window, 'innerWidth', { value: 500, configurable: true });
        window.dispatchEvent(new Event('resize'));
        try {
            await railOn();
            setPages([row()]);
            await settle();
            await press(KEY);
            await settle();
            expect(frames(document.getElementById('plugin-main-view')!), 'no main view on a phone').toEqual([]);
            const steps = Array.from(flyout().querySelectorAll<HTMLElement>('[data-page-step]'));
            expect(steps.map((s) => [s.dataset.pageStep, s.hidden])).toEqual([['menu', false], ['view', true]]);
            expect(frames(flyout()).map((f) => f.dataset.cplugRole)).toEqual(['menu', 'page']);
            const view = flyout().querySelector<HTMLElement>('[data-page-step-key="view"]')!;
            view.click();
            await settle();
            expect(steps.map((s) => s.hidden)).toEqual([true, false]);
        } finally {
            Object.defineProperty(window, 'innerWidth', { value: width, configurable: true });
            window.dispatchEvent(new Event('resize'));
        }
    });

    test('crossing 700 px with the page open swaps cleanly: narrowing leaves no main-view frame behind the slide-out, widening brings the page back', async () => {
        const width = window.innerWidth;
        const resizeTo = async (px: number): Promise<void> => {
            Object.defineProperty(window, 'innerWidth', { value: px, configurable: true });
            window.dispatchEvent(new Event('resize'));
            await settle();
        };
        try {
            await resizeTo(1200);
            await railOn();
            setPages([row()]);
            await settle();
            await press(KEY);
            await settle();
            const main = (): HTMLIFrameElement[] => frames(document.getElementById('plugin-main-view')!);
            expect(main(), 'desktop: the page lies over the main area').toHaveLength(1);
            await resizeTo(500);
            expect(main(), 'phone: no hidden main-view frame left behind').toEqual([]);
            expect(frames(flyout()).map((f) => f.dataset.cplugRole)).toEqual(['menu', 'page']);
            await resizeTo(1200);
            expect(main(), 'widened: the page is back').toHaveLength(1);
            expect(frames(flyout()).map((f) => f.dataset.cplugRole)).toEqual(['menu']);
        } finally {
            Object.defineProperty(window, 'innerWidth', { value: width, configurable: true });
            window.dispatchEvent(new Event('resize'));
        }
    });
});
