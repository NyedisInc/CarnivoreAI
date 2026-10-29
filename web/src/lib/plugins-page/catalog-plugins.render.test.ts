/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { createCatalogPlugins } from './catalog-plugins.svelte';
import type { CatalogHost } from '../catalog/catalog';
import type { InstallRequest, InstalledItem } from '../catalog/types';
import type { ManagerAdapter } from '../manager-frame/types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const PROJECT = '/work/alpha';
const MCP = { name: 'rea', command: 'npx', args: ['-y', 'rea-agents@6.5.0', 'mcp'], env_keys: ['REA_TOKEN'] };

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    localStorage.clear();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

function hostFixture(previewFails = false, fm: Record<string, unknown> | null = null, seed: InstalledItem[] = []): { host: CatalogHost; installs: InstallRequest[]; uninstalls: string[] } {
    let ledger: InstalledItem[] = [...seed];
    const installs: InstallRequest[] = [];
    const uninstalls: string[] = [];
    const host = {
        listItems: async () => ({ items: [{ id: 'rea/rea', kind: 'plugin', name: 'rea', publisher: 'rea', latest: '6.5.0', fm, card: { title: 'Rea', brief: 'an agent plugin' } }] }),
        listInstalled: async () => ({ items: ledger }),
        listProjects: async () => [{ name: 'alpha', path: PROJECT }],
        currentProjectPath: async () => PROJECT,
        previewInstall: async () => {
            if (previewFails) throw new Error('offline');
            return { digest: 'd'.repeat(64), body_sha: 'b'.repeat(64), plan_token: 'tok', files: [{ path: 'SKILL.md' }], mcp_servers: [MCP] };
        },
        install: async (request: InstallRequest) => {
            installs.push(request);
            const row = { install_id: 'inst1', item_id: request.item_id, scope: request.scope, project_path: request.project_path };
            ledger = [...ledger, row];
            return row;
        },
        uninstall: async (id: string) => {
            uninstalls.push(id);
            ledger = ledger.filter((row) => row.install_id !== id);
        },
    } as unknown as CatalogHost;
    return { host, installs, uninstalls };
}

const emptyBuiltins: ManagerAdapter = { list: async () => [] };

async function page(host: CatalogHost, openSheet = vi.fn(async () => null)): Promise<HTMLElement> {
    const catalog = createCatalogPlugins({ host, t, openSheet });
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(PluginsScreen, { target, props: { embedded: true, adapter: emptyBuiltins, catalog } });
    await settle();
    return target;
}

const card = (root: HTMLElement) => root.querySelector('[data-item-id="catalog:rea/rea"]') as HTMLElement;
const sw = (root: HTMLElement) => card(root).querySelector('[role="switch"]') as HTMLElement;

describe('a downloadable plugin on the plugins page', () => {
    test('prints its full MCP command before the switch is touched', async () => {
        const { host } = hostFixture();
        const root = await page(host);
        expect(root.textContent?.toLowerCase()).not.toContain('downloadable');
        const shown = card(root).querySelector('[data-catalog-command]')?.textContent ?? '';
        expect(shown).toContain('npx -y rea-agents@6.5.0 mcp');
        expect(shown).toContain('REA_TOKEN');
        expect(card(root).querySelector('[data-act="add"]')).not.toBeNull();
        expect(sw(root)).toBeNull();
    });

    test('add installs through the warez one-click route; the switch of an installed plugin removes that project row, and add comes back', async () => {
        const { host, installs, uninstalls } = hostFixture(false, null, [{ install_id: 'inst1', item_id: 'rea/rea', scope: 'project', project_path: PROJECT } as InstalledItem]);
        const root = await page(host);
        expect(sw(root).getAttribute('aria-checked')).toBe('true');
        expect(card(root).querySelector('[data-act="add"]')).toBeNull();
        sw(root).click();
        await settle();
        expect(uninstalls).toEqual(['inst1']);
        await settle();
        const add = card(root).querySelector('[data-act="add"]') as HTMLElement;
        expect(add).not.toBeNull();
        add.click();
        await settle();
        expect(installs).toHaveLength(1);
        expect(installs[0]).toMatchObject({ item_id: 'rea/rea', scope: 'global', one_click: true });
        expect(card(root).querySelector('[data-act="add"]')).toBeNull();
    });

    test('a preview that could not be read never installs silently: the install sheet opens', async () => {
        const { host, installs } = hostFixture(true, null, [{ install_id: 'inst2', item_id: 'rea/rea', scope: 'project', project_path: '/work/beta' } as InstalledItem]);
        const openSheet = vi.fn(async () => null);
        const root = await page(host, openSheet);
        expect(card(root).textContent).toContain(t('plugins.page.catalog.preview_failed'));
        sw(root).click();
        await settle();
        expect(installs).toHaveLength(0);
        expect(openSheet).toHaveBeenCalledTimes(1);
    });
});

describe('a downloadable plugin card is the one warez card', () => {
    test('it carries no byline, no source link and no distributed-by line', async () => {
        const fm = { author: 'Ada Lovelace', homepage: 'javascript:alert(1)', repository: 'https://github.com/ada/rea', author_url: 'https://ada.dev' };
        const root = await page(hostFixture(false, fm).host);
        expect(card(root).textContent).not.toContain('by Ada Lovelace');
        expect(card(root).querySelector('[data-catalog-credit]')).toBeNull();
        expect(card(root).querySelector('.cpc__trust')).toBeNull();
        expect(card(root).querySelector('.catalog-card__meta')).toBeNull();
    });
});

describe('a downloadable plugin detail pane', () => {
    test('it draws the credit line: the source link and who distributes it (the pane names CatalogPluginCredit)', async () => {
        const fm = { author: 'Ada Lovelace', repository: 'https://github.com/ada/rea' };
        const root = await page(hostFixture(false, fm).host);
        root.querySelector<HTMLButtonElement>('.catalog-card__open')!.click();
        await settle();
        const credit = root.querySelector('.plugin-catalog-pane [data-catalog-credit]');
        expect(credit, 'the credit line in the detail pane').not.toBeNull();
        expect(credit!.querySelector<HTMLAnchorElement>('.cpc__source')!.href).toBe('https://github.com/ada/rea');
        expect(credit!.querySelector('.cpc__trust')!.textContent).toContain('rea');
    });
});
