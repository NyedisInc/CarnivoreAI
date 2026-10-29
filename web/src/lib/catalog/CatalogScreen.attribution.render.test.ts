/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ensurePanel, unmountPanel } from '../mount';
import type { CatalogHost } from './catalog';
import { CATALOG_SCREEN_CONTAINER } from './screen-host';
import type { CatalogItem } from './types';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const REVIEW = { status: 'reviewed', verdict: 'clean', warnings: [] };
const versions = [{ v: '1.0.0', digest: 'a'.repeat(64), review: REVIEW }];

const ITEMS = [
    {
        id: 'nyedis/rea',
        name: 'rea',
        publisher: 'nyedis',
        latest: '1.0.0',
        kind: 'plugin',
        card: { title: 'Rea', brief: 'a plugin' },
        fm: { author: 'morluto', homepage: 'https://example.com/rea', repository: 'javascript:alert(1)', author_url: null },
        versions,
    },
    { id: 'alex/deploy', name: 'deploy', publisher: 'alex', latest: '1.0.0', kind: 'skill', card: { title: 'Deploy', brief: 'a skill' }, versions },
] as unknown as CatalogItem[];

const host = {
    listItems: () => Promise.resolve({ index: { as_of: '2026-09-15' }, items: ITEMS, untrusted: [] }),
    listInstalled: () => Promise.resolve({ items: [] }),
    runningSessions: () => [],
    listProjects: () => Promise.resolve([]),
    currentProjectPath: () => Promise.resolve(null),
    item: (id: string) => Promise.resolve(ITEMS.find((e) => e.id === id) ?? ({} as CatalogItem)),
} as unknown as CatalogHost;

beforeEach(() => {
    localStorage.removeItem('carnivore.pageview.skills');
    const c = document.createElement('div');
    c.id = CATALOG_SCREEN_CONTAINER;
    document.body.appendChild(c);
});
afterEach(() => {
    unmountPanel(CATALOG_SCREEN_CONTAINER);
    document.body.innerHTML = '';
});

const cardOf = (title: string) =>
    [...document.querySelectorAll('.catalog-card')].find((c) => c.querySelector('.catalog-card__title')?.textContent?.trim() === title) as HTMLElement | undefined;

describe('plugin attribution on the Warez card', () => {
    test('a plugin card and a skill card carry no byline, source or distributed-by line', async () => {
        const Screen = (await import('./CatalogScreen.svelte')).default;
        const handle = ensurePanel(CATALOG_SCREEN_CONTAINER, Screen as never, { host, t } as never) as { show: () => void };
        handle.show();
        await new Promise((r) => setTimeout(r, 0));

        const plugin = cardOf('Rea');
        expect(plugin, 'the plugin card is in the grid').toBeDefined();
        expect(plugin!.querySelector('[data-catalog-author]')).toBeNull();
        expect(plugin!.querySelector('[data-catalog-credit]')).toBeNull();
        expect(plugin!.querySelector('.catalog-card__meta')).toBeNull();

        const skill = cardOf('Deploy');
        expect(skill, 'the skill card is in the grid').toBeDefined();
        expect(skill!.querySelector('[data-catalog-author]')).toBeNull();
        expect(skill!.querySelector('[data-catalog-credit]')).toBeNull();

        expect(document.querySelector('[data-group="kind"] .kind-mark--plugin')).not.toBeNull();
    });
});
