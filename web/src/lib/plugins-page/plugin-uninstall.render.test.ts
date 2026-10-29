/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { createCatalogPlugins } from './catalog-plugins.svelte';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import type { CatalogHost } from '../catalog/catalog';
import type { InstalledItem } from '../catalog/types';
import type { ManagerAdapter } from '../manager-frame/types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const SIDECAR: CplugRow = {
    id: 'warezsmoke', name: 'warezsmoke', description: 'a smoke plugin', version: '1.0.0', runtime: 'sidecar', publisher: 'acme',
    enabled: false, state: 'disabled', storage_bytes: 0, permissions: { app: [] }, grants: { app: [] }, needs: [],
};
const BUILTIN: CplugRow = { id: 'huddle', name_key: 'cplug.huddle.name', version: '1.0.0', tier: 'builtin', enabled: true, state: 'active', permissions: { app: [] }, grants: { app: [] }, needs: [] };
const LEDGER_ROW: InstalledItem = { install_id: 'inst-7041', item_id: 'acme/warezsmoke', kind: 'cplug', scope: 'global', source_index_url: 'https://index.example/x', revision: 1 };

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    localStorage.clear();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

async function open(rows: CplugRow[], ledger: InstalledItem[], openId: string): Promise<{ root: HTMLElement; uninstalls: string[] }> {
    const uninstalls: string[] = [];
    const host = {
        listItems: async () => ({ items: [] }),
        listInstalled: async () => ({ items: ledger }),
        listProjects: async () => [],
        currentProjectPath: async () => null,
        previewInstall: async () => ({}),
        uninstall: async (id: string) => {
            uninstalls.push(id);
        },
    } as unknown as CatalogHost;
    const adapter: ManagerAdapter = { list: async () => rows.map((row) => toCplugItem(row, t)), setEnabled: async () => toCplugItem(rows[0]!, t) };
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginsScreen, { target, props: { embedded: true, adapter, catalog: createCatalogPlugins({ host, t }), t, loadActivity: async () => [] } });
    await settle();
    target.querySelector<HTMLButtonElement>(`[data-item-id="cplug:${openId}"] .catalog-card__open`)!.click();
    await settle();
    return { root: target, uninstalls };
}

describe('uninstall in the plugin pane', () => {
    test('a ledger-backed plugin missing from the index offers uninstall, and the sheet sends the delete', async () => {
        const { root, uninstalls } = await open([SIDECAR], [LEDGER_ROW], 'warezsmoke');
        const button = root.querySelector<HTMLButtonElement>('[data-plugin-uninstall] [data-act="uninstall"]')!;
        expect(button.textContent?.trim()).toBe('uninstall');
        button.click();
        await settle();
        expect(document.body.textContent).toContain('uninstall warezsmoke');
        expect(uninstalls).toEqual([]);
        const confirm = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find((b) => b.textContent?.trim() === 'uninstall it')!;
        confirm.click();
        await settle();
        expect(uninstalls).toEqual(['inst-7041']);
    });

    test('a compiled-in plugin shows no uninstall', async () => {
        const { root } = await open([BUILTIN], [{ ...LEDGER_ROW, item_id: 'carnivore/huddle', source_index_url: 'builtin' }], 'huddle');
        expect(root.querySelector('[data-plugin-pane="huddle"]')).not.toBeNull();
        expect(root.querySelector('[data-plugin-uninstall]')).toBeNull();
    });
});
