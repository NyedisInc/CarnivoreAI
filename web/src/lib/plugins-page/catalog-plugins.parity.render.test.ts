/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { createCatalogPlugins } from './catalog-plugins.svelte';
import type { CatalogHost } from '../catalog/catalog';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const SHA = 'a'.repeat(64);

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

const item = (id: string, title: string, rank: number | null, media = false) => ({
    id,
    kind: 'plugin',
    name: title,
    publisher: 'acme',
    latest: '1.0.0',
    featured_rank: rank,
    card: { title, brief: `${title} brief`, ...(media ? { media: { sha256: SHA } } : {}) },
});

describe('plugins page and warez agree on the card and the order', () => {
    test('hero hash carried, no downloadable word, warez order', async () => {
        const host = {
            listItems: async () => ({ items: [item('acme/clean', 'clean', null), item('acme/mcp', 'mcp', 2), item('acme/rea', 'rea', 1, true)] }),
            listInstalled: async () => ({ items: [] }),
            listProjects: async () => [],
            currentProjectPath: async () => null,
            previewInstall: async () => {
                throw new Error('none');
            },
        } as unknown as CatalogHost;
        const catalog = createCatalogPlugins({ host, t });
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, { target, props: { embedded: true, adapter: { list: async () => [] }, catalog } });
        for (let i = 0; i < 6; i += 1) await Promise.resolve();
        await tick();
        flushSync();
        expect(catalog.items().find((row) => row.itemId === 'acme/rea')?.mediaSha).toBe(SHA);
        expect(target.textContent?.toLowerCase()).not.toContain('downloadable');
        const order = [...target.querySelectorAll('[data-item-id]')].map((el) => el.getAttribute('data-item-id'));
        expect(order).toEqual(['catalog:acme/rea', 'catalog:acme/mcp', 'catalog:acme/clean']);
    });
    test('action slot: add for a plugin with no copy, the switch for an installed one', async () => {
        const host = {
            listItems: async () => ({ items: [item('acme/clean', 'clean', null), item('acme/rea', 'rea', 1)] }),
            listInstalled: async () => ({ items: [{ item_id: 'acme/rea', scope: 'project', project_path: '/p', install_id: 'i1' }] }),
            listProjects: async () => [{ name: 'p', path: '/p' }],
            currentProjectPath: async () => '/p',
            previewInstall: async () => {
                throw new Error('none');
            },
        } as unknown as CatalogHost;
        const catalog = createCatalogPlugins({ host, t });
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, { target, props: { embedded: true, adapter: { list: async () => [] }, catalog } });
        for (let i = 0; i < 8; i += 1) await Promise.resolve();
        await tick();
        flushSync();
        const card = (id: string) => target.querySelector(`[data-item-id="catalog:acme/${id}"]`) as HTMLElement;
        expect(card('clean').querySelector('[data-act="add"]')).not.toBeNull();
        expect(card('clean').querySelector('[role="switch"]')).toBeNull();
        expect(card('rea').querySelector('[role="switch"]')).not.toBeNull();
        expect(card('rea').querySelector('[data-act="add"]')).toBeNull();
    });
});
