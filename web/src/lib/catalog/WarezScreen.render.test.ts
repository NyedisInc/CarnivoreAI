/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';

vi.mock('../../opscenter/api/events.svelte', () => ({
    subscribe: () => () => {},
}));

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ensurePanel, unmountPanel } from '../mount';
import { MENU_PAGES } from '../menu-page/menu-pages';
import type { CatalogHost } from './catalog';
import {
    closeCatalogScreen,
    openCatalogScreen,
    wireCatalogDeepLink,
} from './screen-host';
import type { CatalogItem } from './types';
import { WAREZ_SCREEN_CONTAINER, closeWarezScreen } from './warez-host';
import WarezScreen from './WarezScreen.svelte';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const SKILLS: CatalogItem[] = [
    { id: 'alex/deploy', name: 'deploy', publisher: 'alex', latest: '1.0', kind: 'skill', card: { title: 'Deploy Runner', brief: 'ships a build' } },
    { id: 'zoe/audit', name: 'audit', publisher: 'zoe', latest: '3.1', kind: 'skill', card: { title: 'Security Audit', brief: 'reviews a repo' } },
];
const THEME: CatalogItem = { id: 'ada/neon', name: 'neon', publisher: 'ada', latest: '1', kind: 'theme', card: { title: 'Neon Glass', brief: 'a theme' } };
const MOD: CatalogItem = { id: 'ada/working-on', name: 'working-on', publisher: 'ada', latest: '1', kind: 'mod', card: { title: 'Working On', brief: 'a mod' } };

function hostFor(items: CatalogItem[]): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-10-03T03:41:56+00:00' }, items, untrusted: [] }),
        refreshIndex: refuse,
        listInstalled: () => Promise.resolve({ items: [] }),
        item: refuse,
        runningSessions: () => [],
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
        catalogSession: () => Promise.resolve({ signed_in: false, login: null, provider: null }),
    } as unknown as CatalogHost;
}

async function settle(ms = 0): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, ms));
    await tick();
    flushSync();
    await new Promise((resolve) => setTimeout(resolve, 0));
}

let warez: HTMLElement;
let stopWiring: () => void = () => {};

function mountBoth(items: CatalogItem[]): void {
    ensurePanel(WAREZ_SCREEN_CONTAINER, WarezScreen as never, { host: hostFor(items), t } as never);
}

const kindRows = (): string[] =>
    [...warez.querySelectorAll('[data-group="store"] + [role="group"] [role="treeitem"][data-key^="store/"]')]
        .filter((n) => /^store\/(skills|themes|mods|plugins)$/.test(n.getAttribute('data-key') ?? ''))
        .map((n) => `${n.querySelector('.wm__label')?.textContent?.trim()} ${n.querySelector('.wm__count')?.textContent?.trim()}`);
const pressedRow = (): string | undefined =>
    warez.querySelector('[data-group="store"] + [role="group"] [aria-selected="true"] .wm__label')?.textContent?.trim();

beforeEach(() => {
    (window as unknown as { CloudeWeb: Record<string, unknown> }).CloudeWeb = { closeWarezScreen, closeCatalogScreen };
    localStorage.clear();
    window.location.hash = '';
    warez = document.createElement('div');
    warez.id = WAREZ_SCREEN_CONTAINER;
    document.body.append(warez);
});

afterEach(() => {
    stopWiring();
    stopWiring = () => {};
    closeWarezScreen();
    closeCatalogScreen();
    unmountPanel(WAREZ_SCREEN_CONTAINER);
    document.body.innerHTML = '';
    window.location.hash = '';
});

describe('warez is the catalog page and the old openers land on it', () => {
    test('it renders titled warez, listing every item of every kind with kind chips', async () => {
        mountBoth([...SKILLS, THEME]);
        openCatalogScreen({ kind: 'theme' });
        await settle(30);
        expect(warez.querySelector('.oc-titlebar__title')?.textContent?.trim()).toBe('warez');
        expect([...warez.querySelectorAll('.catalog-card__title')].map((n) => n.textContent?.trim())).toEqual(['Neon Glass']);
        expect(kindRows()).toEqual(['skills 2', 'themes 1', 'mods 0', 'plugins 0']);
        expect(pressedRow()).toBe('themes');
    });

    test('a bare openCatalogScreen() is warez; a skills tab is warez on the skills list, census read as stats', async () => {
        mountBoth(SKILLS);
        openCatalogScreen();
        await settle(30);
        expect(warez.querySelector('.oc-page')).not.toBeNull();
        expect(warez.querySelector('[data-installed-screen="skill"]')).toBeNull();
        openCatalogScreen({ tab: 'census' });
        await settle(60);
        expect(warez.querySelector('[data-installed-screen="skill"]')).not.toBeNull();
        expect(warez.querySelector('#wskills-tab-stats')?.getAttribute('aria-selected')).toBe('true');
    });

    test('opened on mod with no mod published: the chip shows selected and the list says so', async () => {
        mountBoth(SKILLS);
        openCatalogScreen({ kind: 'mod' });
        await settle(30);
        expect(pressedRow()).toBe('mods');
        expect(warez.textContent).toContain('no mods published yet');
        expect(warez.querySelector('.catalog-card')).toBeNull();
    });

    test('opened plain the menu counts every kind, mods 0 until one is published', async () => {
        mountBoth([...SKILLS, THEME]);
        openCatalogScreen();
        await settle(30);
        expect(kindRows()).toEqual(['skills 2', 'themes 1', 'mods 0', 'plugins 0']);
        closeWarezScreen();
        unmountPanel(WAREZ_SCREEN_CONTAINER);
        ensurePanel(WAREZ_SCREEN_CONTAINER, WarezScreen as never, { host: hostFor([...SKILLS, MOD]), t } as never);
        openCatalogScreen();
        await settle(30);
        expect(kindRows()).toEqual(['skills 2', 'themes 0', 'mods 1', 'plugins 0']);
    });
});

describe('the menu drives the page (issue #1904)', () => {
    test('a node press writes its own address and swaps the right pane; the address walks back to the grid', async () => {
        mountBoth([...SKILLS, THEME]);
        stopWiring = wireCatalogDeepLink();
        openCatalogScreen();
        await settle(30);
        expect(warez.querySelector('.catalog-card')).not.toBeNull();
        warez.querySelector<HTMLElement>('[data-key="store/themes"]')!.click();
        await settle(30);
        expect(window.location.hash).toBe('#warez/store/themes');
        expect([...warez.querySelectorAll('.catalog-card__title')].map((n) => n.textContent?.trim())).toEqual(['Neon Glass']);
        warez.querySelector<HTMLElement>('[data-key="installed/themes"]')!.click();
        await settle(30);
        expect(window.location.hash).toBe('#warez/installed/themes');
        expect(warez.querySelector('[data-installed-screen="theme"] .themes-screen')).not.toBeNull();
        expect(warez.querySelector('.catalog-card')).toBeNull();
        window.location.hash = '#warez/store/skills';
        window.dispatchEvent(new Event('hashchange'));
        await settle(60);
        expect(warez.querySelector('[data-installed-screen]')).toBeNull();
        expect([...warez.querySelectorAll('.catalog-card__title')].map((n) => n.textContent?.trim()).sort()).toEqual(['Deploy Runner', 'Security Audit']);
    });
});

describe('the fragments', () => {
    test('#catalog and #catalog/<id> are warez in MENU_PAGES, and the skills entry no longer claims #catalog', () => {
        const page = MENU_PAGES.find((p) => p.id === 'warez');
        expect(page?.containerId).toBe(WAREZ_SCREEN_CONTAINER);
        expect(page?.railItem).toBe('warez');
        expect(page?.hashes).toEqual(['#warez', '#catalog', '#skills', '#skills-manager']);
        expect(MENU_PAGES.find((p) => p.id === 'skills')).toBeUndefined();
    });

    test('#catalog/<id> opens warez on that item and #skills opens warez on the skills list', async () => {
        mountBoth(SKILLS);
        stopWiring = wireCatalogDeepLink();
        window.location.hash = '#catalog/zoe/audit';
        window.dispatchEvent(new Event('hashchange'));
        await settle(60);
        expect(warez.querySelector('.oc-page')).not.toBeNull();
        expect(warez.querySelector('.screen__detail')).not.toBeNull();
        window.location.hash = '#skills';
        window.dispatchEvent(new Event('hashchange'));
        await settle(60);
        expect(warez.querySelector('#wskills-tab-installed')?.getAttribute('aria-selected')).toBe('true');
    });
});

describe('no bands, a pack listed once, and the sort without catalog order', () => {
    const ver = (v: string, at: string) => ({ v, published_at: at });
    const BANDED: CatalogItem[] = [
        { id: 'a/second', name: 'second', publisher: 'a', latest: '1', kind: 'skill', featured_rank: 2, first_published_at: '2026-10-01T00:00:00+00:00', card: { title: 'Second Pick', brief: 'b' } },
        { id: 'a/pack', name: 'pack', publisher: 'a', latest: '1', kind: 'loadout', featured_rank: 1, first_published_at: '2026-10-03T00:00:00+00:00', card: { title: 'Starter Pack', brief: 'b' } },
        { id: 'a/plain', name: 'plain', publisher: 'a', latest: '1', kind: 'skill', first_published_at: '2026-10-02T00:00:00+00:00', card: { title: 'Plain One', brief: 'b' } },
        { id: 'a/bumped', name: 'bumped', publisher: 'a', latest: '2', kind: 'skill', versions: [ver('1', '2026-09-01T00:00:00+00:00'), ver('2', '2026-10-05T00:00:00+00:00')], card: { title: 'Bumped', brief: 'b' } },
        { id: 'a/old', name: 'old', publisher: 'a', latest: '1', kind: 'skill', deprecated: { reason: 'gone' }, featured_rank: 0, card: { title: 'Old Thing', brief: 'b' } },
        { id: 'a/last', name: 'last', publisher: 'a', latest: '1', kind: 'skill', card: { title: 'Last One', brief: 'b' } },
    ] as unknown as CatalogItem[];

    test('no browse bands, the head line, the pack once, no catalog order, the pack in the grid while searching', async () => {
        mountBoth(BANDED);
        openCatalogScreen();
        await settle(30);
        expect(warez.querySelector('[data-warez-highlights]')).toBeNull();
        expect(warez.querySelector('[data-warez-featured]')).toBeNull();
        const head = warez.querySelector('.rows__head');
        expect(head?.textContent).toContain('all warez');
        expect(head?.textContent).toContain('6 of 6');
        expect(warez.querySelectorAll('.cat-packs__card').length).toBe(1);
        expect([...warez.querySelectorAll('.catalog-card__title')].filter((n) => n.textContent?.trim() === 'Starter Pack').length).toBe(0);
        const options = [...warez.querySelectorAll('select option')].map((n) => (n.textContent ?? '').trim());
        expect(options).toContain('featured');
        expect(options.some((o) => o === 'catalog order')).toBe(false);

        const input = warez.querySelector('input[type="search"], input[type="text"]') as HTMLInputElement;
        input.value = 'starter';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await settle(300);
        expect(warez.querySelector('.cat-packs')).toBeNull();
        expect([...warez.querySelectorAll('.catalog-card__title')].map((n) => n.textContent?.trim())).toEqual(['Starter Pack']);
    });
});
