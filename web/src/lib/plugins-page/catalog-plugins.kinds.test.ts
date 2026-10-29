import { describe, expect, test, vi } from 'vitest';

import { createCatalogPlugins, type CatalogPluginsDeps } from './catalog-plugins.svelte';
import type { CatalogHost } from '../catalog/catalog';
import type { Translate } from '../sessions/types';

const t: Translate = (key) => key;

function host(installedIds: string[]): CatalogHost {
    return {
        listItems: async () => ({
            items: [
                { id: 'rea/rea', kind: 'plugin', name: 'rea', publisher: 'rea', latest: '1.0.0', card: { title: 'Rea' } },
                { id: 'carnivore/mcphealth', kind: 'cplug', name: 'mcphealth', publisher: 'carnivore', latest: '1.0.0', card: { title: 'MCP health' } },
                { id: 'carnivore/dark', kind: 'theme', name: 'dark', publisher: 'carnivore', latest: '1.0.0' },
            ],
        }),
        listInstalled: async () => ({ items: installedIds.map((id) => ({ install_id: `i-${id}`, item_id: id, scope: 'global' })) }),
        listProjects: async () => [],
        currentProjectPath: async () => null,
        previewInstall: async () => ({}),
    } as unknown as CatalogHost;
}

describe('downloadable plugins of both kinds', () => {
    test('a {plugin, cplug} catalog is two rows; an installed cplug is one', async () => {
        const both = createCatalogPlugins({ host: host([]), t });
        await both.load();
        expect(both.items().map((i) => i.itemId)).toEqual(['rea/rea', 'carnivore/mcphealth']);

        const installed = createCatalogPlugins({ host: host(['carnivore/mcphealth']), t });
        await installed.load();
        expect(installed.items().map((i) => i.itemId)).toEqual(['rea/rea']);
    });

    test('an uninstalled cplug switch opens the install sheet at global scope', async () => {
        const openSheet = vi.fn<NonNullable<CatalogPluginsDeps['openSheet']>>(async () => null);
        const store = createCatalogPlugins({ host: host([]), t, openSheet });
        await store.load();
        await store.setEnabled('carnivore/mcphealth', true);
        expect(openSheet).toHaveBeenCalledOnce();
        expect(openSheet.mock.calls[0]?.[1]).toEqual({ scope: 'global', projectPath: null });
    });
});
