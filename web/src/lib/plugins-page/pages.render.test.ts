/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import WidgetsScreen from '../widgets-page/WidgetsScreen.svelte';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { isViewCell } from '../../opscenter/widgets/views';
import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
import { createOverlayHost } from '../manager-frame/overlay-host';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { createWidgetsAdapter } from '../widgets-page/widgets-adapter';
import { memoryFetcher } from '../item-settings/memory-fetcher';
import { createItemSettingsController } from '../item-settings/item-settings-controller.svelte';
import type { Fetcher } from '../item-settings/api';
import { PSEUDO_LOCALE } from '../../../../client/js/i18n/pseudo.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const pseudo = createI18n({ locale: PSEUDO_LOCALE }) as { t: Translate };
const tPseudo: Translate = (key, params) => pseudo.t(key, params);

const ROWS: CplugRow[] = [
    { id: 'unread', name_key: 'cplug.unread.name', description_key: 'cplug.unread.description', version: '1.0.0', tier: 'builtin', icon: 'bell', author: 'Alex (Example-owner)', surfaces: { plugins: ['session-card-action'] }, enabled: true, state: 'active', permissions: { app: [] } },
    { id: 'share', name_key: 'cplug.share.name', description_key: 'cplug.share.description', version: '1.0.0', tier: 'builtin', icon: 'no-such-icon', author: 'Joe (ccsliinc)', surfaces: { tabs: ['share'], menu_links: ['share'] }, enabled: false, state: 'disabled', permissions: { app: [] } },
];

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 3; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function show(component: typeof PluginsScreen | typeof WidgetsScreen, props: Record<string, unknown>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(component as typeof PluginsScreen, { target, props: { embedded: true, ...props } });
    await settle();
    return target;
}

function pluginsFixture(tr: Translate = t): { adapter: ManagerAdapter; puts: Array<[string, boolean]> } {
    let rows = ROWS.map((row) => ({ ...row }));
    const puts: Array<[string, boolean]> = [];
    return {
        puts,
        adapter: {
            list: async () => rows.map((row) => toCplugItem(row, tr)),
            setEnabled: async (id: string, enabled: boolean): Promise<ManagerItem> => {
                puts.push([id, enabled]);
                const plain = id.replace(/^cplug:/, '');
                rows = rows.map((row) => (row.id === plain ? { ...row, enabled, state: enabled ? 'active' : 'disabled' } : row));
                return toCplugItem(rows.find((row) => row.id === plain)!, tr);
            },
        },
    };
}

const names = (root: HTMLElement): string[] =>
    Array.from(root.querySelectorAll('.catalog-card__title, .wp-card [data-card-open], .mgr-card__name')).map((el) => el.textContent?.trim() ?? '');

describe('the plugins page', () => {
    afterEach(() => {
        localStorage.clear();
    });

    test('the default grid draws each plugin as the one warez card: 16:9 picture, name, three line brief, no footer', async () => {
        const { adapter } = pluginsFixture();
        const root = await show(PluginsScreen, { adapter, t });
        const cards = Array.from(root.querySelectorAll<HTMLElement>('.catalog-card'));
        expect(cards).toHaveLength(2);
        expect(cards.every((card) => card.getAttribute('data-kind') === 'plugin')).toBe(true);
        expect(cards.map((card) => card.querySelector('.catalog-card__thumb svg')?.getAttribute('data-icon'))).toEqual(['bell', 'plug']);
        expect(cards.every((card) => card.querySelector('.catalog-card__brief') !== null)).toBe(true);
        expect(root.querySelector('.mgr-card__foot, .mgr-card__byline, .catalog-card__meta')).toBeNull();
        expect(root.querySelector('.oc-card-grid')?.classList.contains('warez-grid')).toBe(true);
    });

    test('search finds a plugin by its tag or its author', async () => {
        const { adapter } = pluginsFixture();
        const root = await show(PluginsScreen, { adapter, t });
        const input = root.querySelector('input[type="search"], input') as HTMLInputElement;
        input.value = 'joe';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(names(root)).toEqual(['share read only']);
        input.value = 'session card';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        expect(names(root)).toEqual(['mark unread']);
    });

    test('the grid and list toggle swaps to the 28px rows and remembers the choice', async () => {
        const { adapter } = pluginsFixture();
        const root = await show(PluginsScreen, { adapter, t });
        const buttons = () => Array.from(root.querySelectorAll<HTMLButtonElement>('.oc-page__view .oc-ibtn'));
        expect(buttons().map((b) => b.getAttribute('aria-pressed'))).toEqual(['true', 'false']);
        expect(root.querySelector('.oc-page__items--list')).toBeNull();
        buttons()[1]!.click();
        await settle();
        expect(buttons().map((b) => b.getAttribute('aria-pressed'))).toEqual(['false', 'true']);
        expect(root.querySelector('.oc-page__items--list')).not.toBeNull();
        expect(root.querySelector('.oc-icon-tile')).toBeNull();
        expect(root.querySelector('.mgr-card__foot')).toBeNull();
        expect(root.querySelectorAll('.mgr-card__marks .mgr-mark').length).toBeGreaterThan(0);
        expect(localStorage.getItem('carnivore.view.plugins')).toBe('list');
        unmount(mounted!);
        mounted = null;
        document.body.innerHTML = '';
        const again = await show(PluginsScreen, { adapter: pluginsFixture().adapter, t });
        expect(again.querySelector('.oc-page__items--list')).not.toBeNull();
        expect(again.querySelector<HTMLButtonElement>('.oc-page__view .oc-ibtn[aria-pressed="true"]')?.getAttribute('aria-label')).toBe('list view');
    });

    test('lists every plugin as one kind of row, in words, with a switch in its real state', async () => {
        const { adapter } = pluginsFixture();
        const root = await show(PluginsScreen, { adapter, t });
        expect(names(root)).toEqual(['mark unread', 'share read only']);
        expect(root.querySelector('.oc-titlebar__title')?.textContent?.trim()).toBe('plugins');
        const switches0 = root.querySelectorAll('[role="switch"]');
        expect(switches0).toHaveLength(2);
        const switches = Array.from(root.querySelectorAll('[role="switch"]'));
        expect(switches.map((el) => el.getAttribute('aria-checked'))).toEqual(['true', 'false']);
    });

    test('a switch press goes through setEnabled and shows what came back', async () => {
        const { adapter, puts } = pluginsFixture();
        const root = await show(PluginsScreen, { adapter, t });
        (root.querySelector('[role="switch"]') as HTMLButtonElement).click();
        await settle();
        expect(puts).toEqual([['cplug:unread', false]]);
        expect(root.querySelector('[role="switch"]')?.getAttribute('aria-checked')).toBe('false');
    });

    test('the off chip narrows to the plugins that are off', async () => {
        const { adapter } = pluginsFixture();
        const root = await show(PluginsScreen, { adapter, t });
        const bar = root.querySelector('.oc-toolbar')!;
        const selects = Array.from(bar.querySelectorAll<HTMLSelectElement>('select'));
        const state = selects.find((el) => Array.from(el.options).some((o) => o.textContent?.trim() === 'off'))!;
        state.value = 'off';
        state.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(names(root)).toEqual(['share read only']);
        const order = Array.from(bar.querySelectorAll('.oc-toolbar__search, .oc-toolbar__facets, .oc-toolbar__end')).map((el) => el.className);
        expect(order).toEqual(['oc-toolbar__search', 'oc-toolbar__facets', 'oc-toolbar__end']);
        expect(bar.querySelectorAll('.oc-toolbar__end select').length).toBe(1);
        expect(bar.querySelector('.oc-toolbar__end [data-view]') ?? bar.querySelector('.oc-toolbar__end button')).not.toBeNull();
    });

    test('the detail pane opens on the overview: its state in words, then version and id', async () => {
        const { adapter } = pluginsFixture();
        const root = await show(PluginsScreen, { adapter, t });
        (root.querySelector('.catalog-card__open') as HTMLButtonElement).click();
        await settle();
        expect(root.querySelector('.oc-page__detail [role="tab"][aria-selected="true"]')?.getAttribute('data-tab')).toBe('overview');
        expect(root.querySelector('[data-plugin-now]')?.textContent).toBe('on');
        expect(root.querySelector('[data-plugin-id]')?.textContent).toBe('unread');
        expect(root.querySelector('[data-plugin-pane="unread"]')?.textContent).toContain('1.0.0');
        expect(root.querySelector('.mgr__detail-kicker')?.textContent).toBe('plugin');
        expect(root.querySelector('.mgr__detail-name')?.textContent).toBe('mark unread');
        expect(root.querySelector('.mgr__detail-bar [data-plugin-state]')?.textContent).toBe('on');
        expect(root.querySelector('.mgr__detail-bar [data-plugin-pane-switch="unread"]')?.getAttribute('aria-checked')).toBe('true');
    });

    test('the permissions tab ticks only for a plugin waiting on a grant, each high ask has its own unticked box and nothing grants until all are ticked', async () => {
        const waiting: CplugRow = {
            ...ROWS[0]!, id: 'huddle', name_key: undefined, enabled: true, state: 'needs_approval',
            permissions: { app: ['sessions.read', 'sessions.message', 'agent_writes'] }, grants: { app: [] },
            risks: { 'sessions.read': 'low', 'sessions.message': 'high', agent_writes: 'high' },
            reasons: { 'sessions.message': 'it posts the answers you give in the huddle', agent_writes: 'it files work items for agents' },
        };
        const puts: Array<[string, boolean]> = [];
        const adapter: ManagerAdapter = {
            list: async () => [toCplugItem(waiting, t), toCplugItem(ROWS[0]!, t)],
            setEnabled: async (id: string, enabled: boolean): Promise<ManagerItem> => {
                puts.push([id, enabled]);
                return toCplugItem({ ...waiting, state: 'active' }, t);
            },
        };
        const root = await show(PluginsScreen, { adapter, t, loadActivity: async () => [] });
        const open = (name: string) =>
            Array.from(root.querySelectorAll<HTMLButtonElement>('.catalog-card__open')).find((el) => el.textContent?.includes(name))!.click();
        const tab = (id: string) => root.querySelector<HTMLButtonElement>(`.oc-page__detail [role="tab"][data-tab="${id}"]`)!.click();
        open('mark unread');
        await settle();
        tab('permissions');
        await settle();
        expect(root.querySelector('[data-perm-tick]')).toBeNull();
        expect(root.querySelector('[data-cplug-grant]')).toBeNull();
        open('huddle');
        await settle();
        const ticks = Array.from(root.querySelectorAll<HTMLInputElement>('[data-perm-tick]'));
        expect(ticks.map((el) => el.dataset.permTick)).toEqual(['sessions.message', 'agent_writes']);
        expect(ticks.every((el) => !el.checked)).toBe(true);
        const rowText = (name: string) => root.querySelector(`[data-perm-row="${name}"]`)?.textContent ?? '';
        expect(rowText('sessions.message')).toContain('it posts the answers you give in the huddle');
        expect(rowText('agent_writes')).toContain('it files work items for agents');
        expect(rowText('sessions.read')).toContain('no reason given');
        expect(root.querySelector('[data-perm-row] [title]')).toBeNull();
        expect(root.querySelector('[data-perm-tick="all"], [data-tick-all]')).toBeNull();
        expect(root.querySelector('[data-perm-count]')?.textContent).toBe('0 of 3 granted');
        const grant = root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!;
        expect(grant.textContent?.trim()).toBe('grant 3');
        expect(grant.getAttribute('data-btn') === 'confirm').toBe(true);
        expect(grant.disabled).toBe(true);
        grant.click();
        await settle();
        expect(puts).toEqual([]);
        ticks[0]!.click();
        await settle();
        expect(grant.disabled).toBe(true);
        ticks[1]!.click();
        await settle();
        expect(grant.disabled).toBe(false);
        expect(puts).toEqual([]);
        grant.click();
        await settle();
        expect(puts).toEqual([['cplug:huddle', true]]);
        expect(root.querySelector('[data-perm-log]')).not.toBeNull();
    });

    test('a plugin waiting on a grant carries a needs-approval mark and a not-active status, and the mark opens the pane on its permissions tab without granting', async () => {
        const waiting: CplugRow = {
            ...ROWS[0]!, id: 'huddle', name_key: undefined, enabled: true, state: 'needs_approval',
            permissions: { app: ['sessions.message'] }, grants: { app: [] }, risks: { 'sessions.message': 'high' },
        };
        const puts: Array<[string, boolean]> = [];
        const adapter: ManagerAdapter = {
            list: async () => [toCplugItem(waiting, t), toCplugItem(ROWS[0]!, t)],
            setEnabled: async (id: string, enabled: boolean): Promise<ManagerItem> => {
                puts.push([id, enabled]);
                return toCplugItem(waiting, t);
            },
        };
        const root = await show(PluginsScreen, { adapter, t, loadActivity: async () => [] });
        const marks = root.querySelectorAll<HTMLButtonElement>('[data-plugin-approval-mark]');
        expect(marks).toHaveLength(1);
        expect(marks[0]!.dataset.pluginApprovalMark).toBe('huddle');
        expect(marks[0]!.textContent?.trim()).toBe('needs approval');
        expect(root.querySelector('[data-item-id="cplug:huddle"] .mgr-card__status--warn')?.textContent).toContain('not active yet');
        expect(root.querySelector('[data-perm-sheet]')).toBeNull();
        marks[0]!.click();
        await settle();
        expect(root.querySelector('.oc-page__detail [role="tab"][aria-selected="true"]')?.getAttribute('data-tab')).toBe('permissions');
        expect(root.querySelector('[data-perm-sheet] [data-perm-tick="sessions.message"]')).not.toBeNull();
        expect(puts).toEqual([]);
    });

    test('changed code of a plugin that asks for nothing still offers approve, and approve sends the consent body with no ticks (#2541)', async () => {
        const waiting: CplugRow = {
            ...ROWS[0]!, id: 'devclock', name_key: undefined, enabled: true, state: 'needs_approval', consent_required: true,
            permissions: { app: [] }, grants: { app: [] }, needs: [],
        };
        const grants: Array<[string, string[]]> = [];
        const adapter: ManagerAdapter = { list: async () => [toCplugItem(waiting, t)], setEnabled: async () => toCplugItem(waiting, t) };
        const grant = async (id: string, ticks: string[]): Promise<unknown> => { grants.push([id, ticks]); return null; };
        const root = await show(PluginsScreen, { adapter, t, grant, loadActivity: async () => [] });
        root.querySelector<HTMLButtonElement>('[data-plugin-approval-mark="devclock"]')!.click();
        await settle();
        expect(root.querySelector('[data-perm-sheet]')?.textContent).toContain('its code changed since you approved it');
        const approve = root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!;
        expect(approve).not.toBeNull();
        expect(approve.textContent?.trim()).toBe('approve');
        expect(approve.getAttribute('data-btn') === 'confirm').toBe(true);
        expect(approve.disabled).toBe(false);
        expect(grants).toEqual([]);
        approve.click();
        await settle();
        expect(grants).toEqual([['devclock', []]]);
    });

    test('a tick made for one plugin is gone when the owner opens another plugin waiting on a grant', async () => {
        const waiting = (id: string): CplugRow => ({
            ...ROWS[0]!, id, name_key: undefined, enabled: true, state: 'needs_approval',
            permissions: { app: ['sessions.message'] }, grants: { app: [] }, risks: { 'sessions.message': 'high' },
        });
        const adapter: ManagerAdapter = {
            list: async () => [toCplugItem(waiting('huddle'), t), toCplugItem(waiting('share'), t)],
            setEnabled: async () => toCplugItem(waiting('huddle'), t),
        };
        const root = await show(PluginsScreen, { adapter, t, loadActivity: async () => [] });
        const open = (name: string) =>
            Array.from(root.querySelectorAll<HTMLButtonElement>('.catalog-card__open')).find((el) => el.textContent?.includes(name))!.click();
        open('huddle');
        await settle();
        root.querySelector<HTMLButtonElement>('.oc-page__detail [role="tab"][data-tab="permissions"]')!.click();
        await settle();
        root.querySelector<HTMLInputElement>('[data-perm-tick="sessions.message"]')!.click();
        await settle();
        expect(root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!.disabled).toBe(false);
        open('share');
        await settle();
        expect(root.querySelector('.oc-page__detail [role="tab"][aria-selected="true"]')?.getAttribute('data-tab')).toBe('permissions');
        expect(root.querySelector<HTMLInputElement>('[data-perm-tick="sessions.message"]')!.checked).toBe(false);
        expect(root.querySelector<HTMLButtonElement>('[data-cplug-grant]')!.disabled).toBe(true);
    });

    test('the permissions tab names each ask by tier, and a combined warning shows above them', async () => {
        const row: CplugRow = {
            ...ROWS[0]!, id: 'huddle', name_key: undefined, enabled: false, state: 'needs_approval',
            permissions: { app: ['activity.read', 'network_hosts.write:api.example.com'] }, grants: { app: [] },
            risks: { 'activity.read': 'high', 'network_hosts.write:api.example.com': 'medium' },
            warnings: [{ code: 'sends_transcripts', reads: 'activity.read', host: 'api.example.com' }],
        };
        const adapter: ManagerAdapter = { list: async () => [toCplugItem(row, t)], setEnabled: async () => toCplugItem(row, t) };
        const root = await show(PluginsScreen, { adapter, t, loadActivity: async () => [] });
        root.querySelector<HTMLButtonElement>('.catalog-card__open')!.click();
        await settle();
        root.querySelector<HTMLButtonElement>('.oc-page__detail [role="tab"][data-tab="permissions"]')!.click();
        await settle();
        const rows = Array.from(root.querySelectorAll<HTMLElement>('[data-perm-row]'));
        expect(rows.map((c) => c.dataset.risk)).toEqual(['high', 'medium']);
        expect(rows[1]!.textContent).toContain('send data to api.example.com');
        expect(root.querySelector('[data-perm-warning]')?.textContent).toContain('can send your transcripts');
        expect(root.querySelector('[data-perm-warning]')?.textContent).toContain('api.example.com');
    });

    test('every word on the page comes from the catalog', async () => {
        const { adapter } = pluginsFixture(tPseudo);
        const root = await show(PluginsScreen, { adapter, t: tPseudo });
        expect(root.querySelector('.oc-titlebar__title')?.textContent).not.toBe('plugins');
        expect(root.querySelector('.oc-titlebar__title')?.textContent).toBe(tPseudo('plugins.page.title'));
        expect(names(root)[0]).toBe(tPseudo('cplug.unread.name'));
    });
});

function widgetsFixture(tr: Translate = t): { props: Record<string, unknown>; hidden: string[]; calls: Array<[string, RequestInit | undefined]> } {
    const schemas = Object.fromEntries(Object.values(CORE_MANIFESTS).map((m) => [m.id, m.settings ?? null]));
    const memory = memoryFetcher(schemas);
    const calls: Array<[string, RequestInit | undefined]> = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push([path, init]);
        return memory(path, init);
    }) as Fetcher;
    const hidden: string[] = [];
    return {
        hidden,
        calls,
        props: {
            t: tr,
            adapter: createWidgetsAdapter(tr, CORE_MANIFESTS, fetcher, async () => {}, (id) => hidden.push(id)),
            settingsFor: (id: string) => createItemSettingsController('widget', id, tr, fetcher, async () => {}),
        },
    };
}

const CATEGORY_SECTIONS = '[data-wp-section]:not([data-wp-section="in-bars"])';

describe('the widgets page', () => {
    const cards = Object.values(CORE_MANIFESTS).filter((m) => !isViewCell(m));
    const total = cards.length;
    const singletons = cards.filter((m) => m.instancing === 'singleton').length;

    test('lists every core widget; the switch lives in the detail pane, for a singleton and not for a per-target kind', async () => {
        const root = await show(WidgetsScreen, widgetsFixture().props);
        expect(total).toBeGreaterThanOrEqual(12);
        expect(root.querySelectorAll(`${CATEGORY_SECTIONS} .wp-card`).length).toBe(total);
        expect(singletons).toBeLessThan(total);
        expect(root.querySelectorAll(`${CATEGORY_SECTIONS} .wp-card [role="switch"]`).length).toBe(0);
        const open = async (m: (typeof cards)[number]) => {
            const btn = root.querySelector<HTMLButtonElement>(`${CATEGORY_SECTIONS} [data-item-id="${m.id}"] [data-card-open]`)!;
            expect(btn, m.id).toBeTruthy();
            btn.click();
            await settle();
            await settle();
        };
        await open(cards.find((m) => m.instancing === 'singleton')!);
        expect(root.querySelectorAll('[data-widget-pane] [role="switch"]').length).toBe(1);
        await open(cards.find((m) => m.instancing === 'per-target')!);
        expect(root.querySelectorAll('[data-widget-pane] [role="switch"]').length).toBe(0);
        expect(names(root)).toContain(t('opscenter.cell.notes.title'));
    });

    test('switching a widget off writes enabled false, shows the answer, and hides it here', async () => {
        const fixture = widgetsFixture();
        const root = await show(WidgetsScreen, fixture.props);
        const card = Array.from(root.querySelectorAll('.wp-card')).find((el) =>
            el.querySelector('[data-card-open]')?.textContent?.trim() === t('opscenter.cell.notes.title'))!;
        card.querySelector<HTMLButtonElement>('[data-card-open]')!.click();
        await settle();
        const toggle = root.querySelector<HTMLButtonElement>('[data-widget-pane] [role="switch"]')!;
        expect(toggle.getAttribute('aria-checked')).toBe('true');
        toggle.click();
        await settle();
        await settle();
        const patch = fixture.calls.find(([, init]) => init?.method === 'PATCH')!;
        expect(patch[0]).toBe('/item-settings/widget/core.notes');
        expect(JSON.parse(String(patch[1]!.body))).toEqual({ enabled: false });
        expect(toggle.getAttribute('aria-checked')).toBe('false');
        expect(fixture.hidden).toEqual(['core.notes']);
    });

    test('each category section holds exactly that category\'s cards', async () => {
        const root = await show(WidgetsScreen, widgetsFixture().props);
        const live = Object.values(CORE_MANIFESTS).filter((m) => m.category === 'live').length;
        expect(live).toBeGreaterThan(0);
        expect(root.querySelectorAll('[data-wp-section="live"] .wp-card').length).toBe(live);
        expect(root.querySelectorAll('[data-wp-section="overview"] .wp-card').length).not.toBe(total);
    });

    test('the detail pane opens on the description card, then the id and what it can do; no form for a widget with no settings', async () => {
        const root = await show(WidgetsScreen, widgetsFixture().props);
        (root.querySelector(`${CATEGORY_SECTIONS} [data-card-open]`) as HTMLButtonElement).click();
        await settle();
        const pane = root.querySelector('[data-widget-pane]')!;
        expect(pane).not.toBeNull();
        expect(pane.getAttribute('data-widget-pane')).toContain('core.');
        expect(pane.querySelector('.pn-sub')?.textContent).not.toBe('');
        expect(pane.querySelector('.pn-brief')?.textContent).not.toBe('');
        expect(pane.querySelector('[data-sec="options"] .pn-none')).not.toBeNull();
        expect(root.querySelector('[data-settings-form]')).toBeNull();
    });

    test('the activity log detail pane shows its generated settings form and saves through the route', async () => {
        const fixture = widgetsFixture();
        const root = await show(WidgetsScreen, fixture.props);
        const open = Array.from(root.querySelectorAll<HTMLButtonElement>('[data-card-open]')).find((el) =>
            el.textContent?.trim() === t(CORE_MANIFESTS['core.activity-log']!.titleKey))!;
        expect(open, 'the activity log card').toBeTruthy();
        open.click();
        await settle();
        await settle();
        const form = root.querySelector('[data-settings-form]')!;
        expect(form.querySelector('.sf__label')?.textContent).toBe(t('widgets.setting.activity_log.show_system'));
        const toggle = form.querySelector<HTMLButtonElement>('[data-setting="showSystem"] [role="switch"]')!;
        expect(toggle.getAttribute('aria-checked')).toBe('true');
        toggle.click();
        await settle();
        await settle();
        const patch = fixture.calls.find(([, init]) => init?.method === 'PATCH')!;
        expect(patch[0]).toBe('/item-settings/widget/core.activity-log');
        expect(JSON.parse(String(patch[1]!.body))).toEqual({ values: { showSystem: false }, expected_revision: 0 });
        expect(toggle.getAttribute('aria-checked')).toBe('false');
        expect(form.querySelector('[data-sf-reset]')).not.toBeNull();
    });

    test('every word on the page comes from the catalog', async () => {
        const root = await show(WidgetsScreen, widgetsFixture(tPseudo).props);
        expect(root.querySelector('.oc-titlebar__title')?.textContent).toBe(tPseudo('widgets.page.title'));
        const titles = Array.from(root.querySelectorAll('.wp-sectionlabel__label')).map((el) => el.textContent?.trim());
        expect(titles).toContain(tPseudo('widgets.page.category.live'));
        expect(titles).not.toContain('live');
    });
});

describe('the overlay host', () => {
    test('opens on its hash, ignores another, and closes when the hash leaves', async () => {
        const target = document.createElement('div');
        target.id = 'plugins-test-screen';
        document.body.append(target);
        const { adapter } = pluginsFixture();
        const Wrapped = ((anchor: unknown, props: Record<string, unknown>) =>
            (PluginsScreen as unknown as (a: unknown, p: Record<string, unknown>) => unknown)(anchor, { ...props, adapter, t })) as unknown as typeof PluginsScreen;
        const host = createOverlayHost('plugins-test-screen', Wrapped as never, '#plugins-test');
        expect(host.isHash('#plugins-test')).toBe(true);
        expect(host.isHash('#plugins')).toBe(false);

        window.location.hash = '#plugins-test';
        const stop = host.wireDeepLink(window);
        await settle();
        expect(target.querySelector('.oc-titlebar__title')?.textContent?.trim()).toBe('plugins');

        window.location.hash = '#somewhere-else';
        window.dispatchEvent(new HashChangeEvent('hashchange'));
        await settle();
        expect(target.querySelector('.mgr')).toBeNull();
        stop();
        host.unmount();
        vi.restoreAllMocks();
    });
});
