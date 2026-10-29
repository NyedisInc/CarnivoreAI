/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';

vi.mock('../../opscenter/api/events.svelte', () => ({ subscribe: () => () => {} }));

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ensurePanel, unmountPanel } from '../mount';
import type { CatalogHost } from './catalog';
import { createCatalogData } from './catalog-data.svelte';
import { closeCatalogScreen, openCatalogScreen } from './screen-host';
import type { CatalogItem, InstalledItem } from './types';
import { WAREZ_SCREEN_CONTAINER, closeWarezScreen } from './warez-host';
import WarezScreen from './WarezScreen.svelte';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const SKILL: CatalogItem = { id: 'alex/deploy', name: 'deploy', publisher: 'alex', latest: '1.0', kind: 'skill', card: { title: 'Deploy Runner', brief: 'ships a build' } };
const row = (item_id: string, kind: string, source_index_url: string): InstalledItem =>
    ({ install_id: `i-${item_id}`, item_id, kind, name: item_id, version: '1.0.0', scope: 'global', source_index_url }) as InstalledItem;
const LEDGER: InstalledItem[] = [
    row('alex/deploy', 'skill', 'https://index.example/v1'),
    row('nyedis/flow', 'cplug', 'builtin'),
    row('carnivore/huddle', 'skill', 'bundled'),
];

function hostFor(): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-10-03T03:41:56+00:00' }, items: [SKILL], untrusted: [] }),
        refreshIndex: refuse,
        listInstalled: () => Promise.resolve({ items: LEDGER }),
        item: refuse,
        runningSessions: () => [],
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
        catalogSession: () => Promise.resolve({ signed_in: false, login: null, provider: null }),
    } as unknown as CatalogHost;
}

async function settle(ms = 0): Promise<void> {
    await new Promise((r) => setTimeout(r, ms));
    await tick();
    flushSync();
    await new Promise((r) => setTimeout(r, 0));
}

let warez: HTMLElement;

beforeEach(() => {
    (window as unknown as { CloudeWeb: Record<string, unknown> }).CloudeWeb = { closeWarezScreen, closeCatalogScreen };
    localStorage.clear();
    window.location.hash = '';
    warez = document.createElement('div');
    warez.id = WAREZ_SCREEN_CONTAINER;
    document.body.append(warez);
});

afterEach(() => {
    closeWarezScreen();
    closeCatalogScreen();
    unmountPanel(WAREZ_SCREEN_CONTAINER);
    document.body.innerHTML = '';
    window.location.hash = '';
});

describe('the warez page lists store items only', () => {
    test('the ledger the page reads drops the rows the app wrote itself and keeps the store row', async () => {
        const data = createCatalogData(hostFor(), t);
        await data.refresh();
        expect((data.ledger ?? []).map((r) => r.item_id)).toEqual(['alex/deploy']);
        expect(Object.keys(data.installed)).toEqual(['alex/deploy']);
    });

    test('the page draws no built-in group and no built-in card, and the store card still renders', async () => {
        ensurePanel(WAREZ_SCREEN_CONTAINER, WarezScreen as never, { host: hostFor(), t } as never);
        openCatalogScreen();
        await settle(40);
        expect(warez.querySelector('[data-builtin], [data-builtin-group], .builtin-mark')).toBeNull();
        expect(warez.textContent?.toLowerCase()).not.toContain('built into the app');
        const titles = [...warez.querySelectorAll('article.catalog-card .catalog-card__title')].map((n) => n.textContent?.trim());
        expect(titles).toEqual(['Deploy Runner']);
    });
});
