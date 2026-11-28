/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('./places-writes', () => ({
    addToPlace: vi.fn(async () => true),
    removeFromPlace: vi.fn(async () => true),
    moveInPlace: vi.fn(),
    resetBars: vi.fn(async () => {}),
}));

import WidgetsScreen from './WidgetsScreen.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { taskmanagerCplug } from '../../plugins/taskmanager';
import { registerCplugWidgets, unregisterCplugWidgets } from '../../plugins/host/widgets';
import { setPanels, type PanelRow } from '../cplug-ui/panel-views.svelte';
import { t } from '../i18n/index.svelte';
import type { Fetcher } from '../item-settings/api';
import { memoryFetcher } from '../item-settings/memory-fetcher';
import { pluginsStore } from '../plugins/store.svelte';
import { stubResizeObserver } from './settings/mock-test-support';
import { allWidgetManifests, createWidgetsAdapter } from './widgets-adapter';

stubResizeObserver();

const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
proto['showPopover'] ??= function () {};
proto['hidePopover'] ??= function () {};

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    setPanels([]);
    unregisterCplugWidgets(taskmanagerCplug);
    pluginsStore.resetForTest();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

describe('widgets-adapter unified widget catalog', () => {
    test('merges core + compiled plugin + sidecar panel + declarative widgets dynamically and drops unregistered ones', async () => {
        const fetcher = vi.fn(async () => ({ widgets: [] })) as unknown as Fetcher;
        const adapter = createWidgetsAdapter(t, undefined, fetcher, async () => {}, () => {});

        const baseIds = (await adapter.list()).map((item) => item.id);
        expect(baseIds).toContain('core.notes');
        expect(baseIds).not.toContain('huddle.chat');
        expect(baseIds).not.toContain('hello.game');
        expect(baseIds).not.toContain('zero.clock');

        registerCplugWidgets(taskmanagerCplug);
        const sidecarRow: PanelRow = {
            id: 'hello',
            runtime: 'sidecar',
            enabled: true,
            state: 'active',
            name: 'Hello',
            install_key: 'k1',
            views: [{ name: 'game', surfaces: ['panel'] }],
        } as unknown as PanelRow;
        const declRow: PanelRow = {
            id: 'zero',
            runtime: 'sidecar',
            enabled: true,
            state: 'active',
            name: 'Zero',
            install_key: 'k2',
            declarative_widget: { id: 'clock', title: 'Zero Clock', sizes: ['medium'] },
        } as unknown as PanelRow;
        setPanels([sidecarRow, declRow]);

        const merged = allWidgetManifests();
        expect(merged['core.notes']).toBeDefined();
        expect(merged['huddle.chat']).toBeDefined();
        expect(merged['hello.game']).toBeDefined();
        expect(merged['zero.clock']).toBeDefined();

        const liveIds = (await adapter.list()).map((item) => item.id);
        expect(liveIds).toContain('core.notes');
        expect(liveIds).toContain('huddle.chat');
        expect(liveIds).toContain('hello.game');
        expect(liveIds).toContain('zero.clock');

        unregisterCplugWidgets(taskmanagerCplug);
        setPanels([{ ...sidecarRow, enabled: false }, { ...declRow, enabled: false }]);

        const afterIds = (await adapter.list()).map((item) => item.id);
        expect(afterIds).toContain('core.notes');
        expect(afterIds).not.toContain('huddle.chat');
        expect(afterIds).not.toContain('hello.game');
        expect(afterIds).not.toContain('zero.clock');
    });

    test('respects an explicit manifests argument without mixing in dynamic plugin manifests', async () => {
        registerCplugWidgets(taskmanagerCplug);
        const fetcher = vi.fn(async () => ({ widgets: [] })) as unknown as Fetcher;
        const adapter = createWidgetsAdapter(t, CORE_MANIFESTS, fetcher, async () => {}, () => {});

        const ids = (await adapter.list()).map((item) => item.id);
        expect(ids).toContain('core.notes');
        expect(ids).not.toContain('huddle.chat');
    });

    test('WidgetsScreen reloads reactively when panels.list or pluginsStore.rows updates while open', async () => {
        const schemas = Object.fromEntries(Object.values(CORE_MANIFESTS).map((m) => [m.id, m.settings ?? null]));
        const fetcher = memoryFetcher(schemas) as Fetcher;
        const adapter = createWidgetsAdapter(t, undefined, fetcher, async () => {}, () => {});

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(WidgetsScreen, {
            target,
            props: { embedded: true, t, previews: false, adapter },
        });
        await settle();

        expect(target.querySelector('[data-item-id="zero.clock"]')).toBeNull();

        const declRow: PanelRow = {
            id: 'zero',
            runtime: 'sidecar',
            enabled: true,
            state: 'active',
            name: 'Zero',
            install_key: 'k2',
            declarative_widget: { id: 'clock', title: 'Zero Clock', sizes: ['medium'] },
        } as unknown as PanelRow;
        setPanels([declRow]);
        await settle();
        expect(target.querySelector('[data-item-id="zero.clock"]')).not.toBeNull();

        registerCplugWidgets(taskmanagerCplug);
        pluginsStore.rows = [{ id: 'taskmanager', enabled: true, state: 'active' } as never];
        await settle();
        expect(target.querySelector('[data-item-id="huddle.chat"]')).not.toBeNull();

        unregisterCplugWidgets(taskmanagerCplug);
        setPanels([{ ...declRow, enabled: false }]);
        pluginsStore.rows = [{ id: 'taskmanager', enabled: false, state: 'disabled' } as never];
        await settle();
        expect(target.querySelector('[data-item-id="zero.clock"]')).toBeNull();
        expect(target.querySelector('[data-item-id="huddle.chat"]')).toBeNull();
    });
});
