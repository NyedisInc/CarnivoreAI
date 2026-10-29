/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { CplugRow } from '../plugins-page/cplugs-adapter';

vi.mock('./api', () => ({
    fetchViewTicket: vi.fn(async () => ({ path: '/cplugs/hello/view/game/t/index.html' })),
    callViewRoute: vi.fn(),
}));

import PanelCell from './PanelCell.svelte';
import { fitsOf, landingFit, livePanelManifests, panelEntries, setPanels } from './panel-views.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { fitsFor } from '../../opscenter/widgets/fits';
import { pluginKindMeta, panels as panelProvider } from '../../opscenter/engine/plugin-kinds';
import { registerPluginKind } from '../../opscenter/engine/plugin-kinds';
import { drawerGroups, groupRows } from '../../opscenter/layout-editor/drawer-groups';
import { widgetInfo } from '../../opscenter/widgets/info/widget-info';
import { t } from '../i18n/index.svelte';
import type { CellMeta, SlotId } from '../../opscenter/engine/types';

const row = (over: Partial<CplugRow>): CplugRow => ({
    id: 'hello', runtime: 'sidecar', enabled: true, state: 'active', name: '<img src=x onerror=alert(1)>', install_key: 'k1', unverified: true,
    views: [{ name: 'game', surfaces: ['panel', 'overlay'] }], ...over,
} as unknown as CplugRow);

let cell: ReturnType<typeof mount> | null = null;
afterEach(() => { if (cell) unmount(cell); cell = null; document.body.innerHTML = ''; setPanels([]); });

describe('panel view sizes (#2184)', () => {
    test('a view registers the fits it declares, the default when it declares none, and lands at large else its smallest size', () => {
        setPanels([row({ views: [{ name: 'game', surfaces: ['panel'] }, { name: 'tiny', surfaces: ['panel'], fits: { sizes: ['wide', 'small'], min: { w: 1, h: 1 }, anySize: true } }] })]);
        const dflt = fitsFor('hello.game' as never, pluginKindMeta('hello.game') as CellMeta);
        expect([dflt.sizes, dflt.anySize, dflt.min]).toEqual([['medium', 'large', 'full'], true, { w: 3, h: 3 }]);
        const tiny = fitsFor('hello.tiny' as never, pluginKindMeta('hello.tiny') as CellMeta);
        expect([tiny.sizes, tiny.anySize, tiny.min]).toEqual([['small', 'wide'], true, { w: 1, h: 1 }]);
        expect(panelProvider().fit('hello.game')).toEqual({ w: 6, h: 5 });
        expect(panelProvider().fit('hello.tiny')).toEqual({ w: 1, h: 1 });
        expect(landingFit(fitsOf({ sizes: ['medium', 'large'] }))).toEqual({ w: 6, h: 5 });
    });

    test('a fits that is not clean falls back and a floor is clamped, never trusted raw', () => {
        expect(fitsOf({ sizes: ['huge'] }).sizes).toEqual(['medium', 'large', 'full']);
        expect(fitsOf({ sizes: [] }).anySize).toBe(true);
        expect(fitsOf({ sizes: ['medium'], min: { w: 9, h: 1.5 } }).min).toEqual({ w: 4, h: 4 });
    });
});

describe('panel views as widgets', () => {
    test('a panel view is a widget that mounts ViewFrame; off yields nothing and unmounts the frame', async () => {
        expect(panelEntries([row({ enabled: false }), row({ views: [{ name: 'game', surfaces: ['overlay'] }] }), row({ state: 'stopped' })])).toEqual([]);
        setPanels([row({})]);
        expect(Object.keys(livePanelManifests())).toEqual(['hello.game']);
        cell = mount(PanelCell, { target: document.body, props: { instance: 'hello.game:panel-k1' } });
        await tick(); await tick();
        const frame = document.querySelector<HTMLIFrameElement>('iframe[data-cplug-view="game"]');
        expect(frame?.getAttribute('sandbox')).toBe('allow-scripts');
        expect(document.querySelector('[data-cplug-name]')?.textContent).toBe('<img src=x onerror=alert(1)>');
        expect(document.querySelector('[data-cplug-box] img')).toBeNull();
        setPanels([row({ enabled: false })]);
        flushSync();
        expect(Object.keys(livePanelManifests())).toEqual([]);
        expect(document.querySelector('iframe')).toBeNull();
        expect(document.querySelector('[data-panel-cell] [role="status"]')).not.toBeNull();
    });

    test('a slot placed for one install shows the off note for another install of the same name and view (L1)', async () => {
        setPanels([row({ install_key: 'other-install' })]);
        cell = mount(PanelCell, { target: document.body, props: { instance: 'hello.game:panel-k1' } });
        await tick(); await tick();
        expect(document.querySelector('iframe')).toBeNull();
        expect(document.querySelector('[data-panel-cell] [role="status"]')).not.toBeNull();
    });

    test('a kind a compiled widget owns, a core id and a folded duplicate name are skipped (L3, L4)', () => {
        registerPluginKind('huddle.chat' as never, { id: 'huddle.chat:x' as SlotId } as CellMeta);
        const views = [{ name: 'my_view', surfaces: ['panel'] }, { name: 'my-view', surfaces: ['panel'] }];
        const kinds = panelEntries([
            row({ id: 'huddle', views: [{ name: 'chat', surfaces: ['panel'] }] }),
            row({ id: 'core', views: [{ name: 'game', surfaces: ['panel'] }] }),
            row({ id: 'dup', views }),
        ]).map((entry) => entry.kind);
        expect(kinds).toEqual(['dup.my-view']);
    });

    test('a placed panel row reads placed in the drawer even though it is a family (L2)', () => {
        setPanels([row({})]);
        const input = (onSurface: SlotId[]) => ({ onSurface, disabled: () => false, t: (key: string) => key }) as never;
        const find = (onSurface: SlotId[]) => groupRows(input(onSurface)).find((r) => r.widgetId === 'hello.game');
        expect(find([])?.state).toBe('addable');
        expect(find(['hello.game:panel-k1' as SlotId])?.state).toBe('placed');
    });
});

describe('panel views in the widget drawer (#2379 follow-up)', () => {
    const info = () => widgetInfo(livePanelManifests()['hello.game']!);

    test('the about text is the plugin\'s own description, else the plain plugin-view line, never a raw key', () => {
        setPanels([row({ description: 'pop the pills' })]);
        expect(t(info().about.key)).toBe('pop the pills');
        expect(info().data.key).toBe('widgets.info.data.plugin_view');
        expect(t(info().data.key)).not.toBe(info().data.key);
        setPanels([row({})]);
        expect(info().about.key).toBe('widgets.info.about.plugin_view');
        expect(t(info().about.key)).not.toBe('widgets.info.about.plugin_view');
        expect(widgetInfo(CORE_MANIFESTS['core.notes']!).about.key).toBe('widgets.info.about.notes');
    });

    test('a panel kind is listed under the plugins heading as a plugin view, a built-in keeps its group', () => {
        setPanels([row({})]);
        const groups = drawerGroups({ onSurface: [], disabled: () => false, query: '', t: (key: string) => key }).groups;
        const where = (id: string) => groups.find((g) => g.rows.some((r) => r.widgetId === id));
        expect(where('hello.game')?.category).toBe('plugins');
        expect(groups.find((g) => g.category === 'plugins')?.rows[0]?.type).toBe('plugin');
        expect(where('core.notes')?.category).toBe(CORE_MANIFESTS['core.notes']!.category);
    });
});
