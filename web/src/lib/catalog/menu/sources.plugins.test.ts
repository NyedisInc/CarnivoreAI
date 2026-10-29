/** @vitest-environment jsdom */
import { describe, expect, test, vi } from 'vitest';

vi.mock('../../../opscenter/api/events.svelte', () => ({ subscribe: () => () => {} }));
vi.mock('../../plugins-page/cplugs-adapter', async (importActual) => ({
    ...(await importActual<Record<string, unknown>>()),
    listCplugItems: () =>
        Promise.resolve([
            { cplugId: 'huddle', name: 'task manager', tier: 'builtin', state: 'active' },
            { cplugId: 'rea', name: 'rea', tier: 'third_party', state: 'disabled' },
            { cplugId: 'mcphealth', name: 'mcp health', tier: 'optional', state: 'active' },
            { cplugId: 'warezsmoke', name: 'warez smoke', tier: 'third_party', state: 'removed' },
        ]),
}));
vi.mock('../../skills-page/skills-api', () => ({ fetchInventory: () => Promise.reject(new Error('unused')) }));

import { createI18n } from '../../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from '../catalog';
import { createCatalogData } from '../catalog-data.svelte';
import { createMenuData } from './sources.svelte';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

describe('installed plugins in the menu', () => {
    test('counts the non-built-in plugins /cplugs gives (sidecars too) plus the store plugins the page draws', async () => {
        const host = {
            listItems: () => Promise.resolve({ index: { as_of: '2026-10-03T03:41:56+00:00' }, items: [{ id: 'acme/clean-tv', name: 'clean your tv', publisher: 'acme', latest: '1.0', kind: 'plugin' }], untrusted: [] }),
            listInstalled: () => Promise.resolve({ items: [] }),
            listProjects: () => Promise.resolve([]),
            currentProjectPath: () => Promise.resolve(null),
            catalogSession: () => Promise.resolve({ signed_in: false, login: null, provider: null }),
        } as unknown as CatalogHost;
        const data = createCatalogData(host, t);
        await data.refresh();
        const menu = createMenuData(data, t);
        await menu.reload();
        expect(menu.sources.installed.plugin.map((e) => e.title).sort()).toEqual(['clean your tv', 'mcp health', 'rea', 'warez smoke']);
    });
});
