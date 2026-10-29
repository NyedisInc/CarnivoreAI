/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { ensurePanel, unmountPanel } from '../mount';
import type { CatalogHost } from './catalog';
import { sortCards } from './sort';
import { cardViews } from './card';
import { openCatalogScreen } from './screen-host';
import { WAREZ_SCREEN_CONTAINER, closeWarezScreen } from './warez-host';
import WarezScreen from './WarezScreen.svelte';
import WarezCensus from './WarezCensus.svelte';
import type { CatalogItem } from './types';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ITEMS: CatalogItem[] = [
    ...Array.from({ length: 7 }, (_, i) => ({ id: `a/skill${i}`, kind: 'skill', name: `skill${i}` })),
    ...Array.from({ length: 16 }, (_, i) => ({ id: `a/theme${i}`, kind: 'theme', name: `theme${i}` })),
    { id: 'a/mod0', kind: 'mod', name: 'mod0' },
].map((item, n) => ({
    ...item,
    publisher: 'a',
    latest: '1',
    first_published_at: `2026-09-${String(n + 1).padStart(2, '0')}T00:00:00+00:00`,
    card: { title: `Title ${item.name}`, brief: 'b' },
}));

const COUNTS: Record<string, number> = { 'a/theme3': 40, 'a/skill0': 7, 'a/mod0': 3, 'a/theme9': 0 };

const batchCalls: string[][] = [];

function hostFor(read: (ids: readonly string[]) => Promise<unknown>): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: () => Promise.resolve({ index: { as_of: '2026-10-03T03:41:56+00:00' }, items: ITEMS, untrusted: [] }),
        refreshIndex: refuse,
        listInstalled: () => Promise.resolve({ items: [] }),
        item: refuse,
        installCounts: (ids: readonly string[]) => {
            batchCalls.push([...ids]);
            return read(ids);
        },
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

async function mountWith(read: (ids: readonly string[]) => Promise<unknown>): Promise<void> {
    ensurePanel(WAREZ_SCREEN_CONTAINER, WarezScreen as never, { host: hostFor(read), t } as never);
    openCatalogScreen();
    await settle(60);
}

beforeEach(() => {
    batchCalls.length = 0;
    localStorage.clear();
    window.location.hash = '';
    warez = document.createElement('div');
    warez.id = WAREZ_SCREEN_CONTAINER;
    document.body.append(warez);
});

afterEach(() => {
    closeWarezScreen();
    unmountPanel(WAREZ_SCREEN_CONTAINER);
    document.body.innerHTML = '';
});

describe('the census band', () => {
    test('no tiles, newest, most downloaded, no serial line', async () => {
        await mountWith((ids) =>
            Promise.resolve({ items: Object.fromEntries(ids.filter((id) => id in COUNTS).map((id) => [id, { count: COUNTS[id], by_version: {} }])) }),
        );
        expect(batchCalls).toHaveLength(1);
        expect(batchCalls[0]).toHaveLength(ITEMS.length);
        const band = warez.querySelector('[data-warez-census]');
        expect(band).not.toBeNull();
        expect(band!.querySelectorAll('.oc-tile')).toHaveLength(0);
        expect(band!.textContent).not.toContain('24 items');
        const text = band!.textContent ?? '';
        expect(text.indexOf('Title mod0')).toBeGreaterThan(-1);
        expect(text.indexOf('Title theme3')).toBeLessThan(text.indexOf('Title skill0'));
        expect(text).toMatch(/Title theme9[^]*0\s*installs/);
        expect(warez.textContent).not.toContain('serial');
    });

    test('with every count unreadable the downloaded list is not drawn', async () => {
        await mountWith(() => Promise.reject(new Error('down')));
        expect(warez.querySelector('[data-warez-census]')).not.toBeNull();
        const band = warez.querySelector('[data-warez-census]')!.textContent ?? '';
        expect(band).toContain('first published');
        expect(band).not.toContain('installs');
    });

    test('with every count a measured 0 the downloaded list is not drawn', async () => {
        await mountWith((ids) => Promise.resolve({ items: Object.fromEntries(ids.map((id) => [id, { count: 0 }])) }));
        const band = warez.querySelector('[data-warez-census]')!.textContent ?? '';
        expect(band).toContain('first published');
        expect(band).not.toContain('installs');
    });
});

describe('the census band follows the KIND filter', () => {
    const draw = (kind: string | null) => {
        const host = document.createElement('div');
        document.body.append(host);
        const app = mount(WarezCensus as never, { target: host, props: { items: ITEMS, kind, installs: new Map(), t } as never });
        flushSync();
        return { host, done: () => unmount(app) };
    };

    test('no heading, side padding, no kind tiles when the kind is all', () => {
        const { host, done } = draw(null);
        const band = host.querySelector('[data-warez-census]') as HTMLElement;
        expect(host.textContent?.toLowerCase()).not.toContain('warez census');
        expect(host.querySelector('.oc-kit-label h2')).toBeNull();
        expect(band.classList.contains('wz-census')).toBe(true);
        expect(readFileSync('src/lib/catalog/WarezCensus.svelte', 'utf8')).toMatch(/\.wz-census\s*\{[^}]*padding-inline:\s*var\(--oc-page-gutter, 16px\)/);
        expect(host.querySelectorAll('.oc-tile')).toHaveLength(0);
        expect(host.textContent).toContain('Title mod0');
        done();
    });

    test('one kind shows no tile and only its newest', () => {
        const { host, done } = draw('skill');
        expect(host.querySelectorAll('.oc-tile')).toHaveLength(0);
        expect(host.textContent).toContain('Title skill6');
        expect(host.textContent).not.toContain('Title theme');
        expect(host.textContent).not.toContain('Title mod0');
        done();
    });
});

describe('the downloaded sort', () => {
    test('orders by install count, highest first, unread last', () => {
        const cards = cardViews(ITEMS, false);
        const counts = new Map(Object.entries(COUNTS));
        const ids = sortCards(cards, 'downloaded', ITEMS, counts).map((c) => c.id);
        expect(ids.slice(0, 4)).toEqual(['a/theme3', 'a/skill0', 'a/mod0', 'a/theme9']);
        expect(ids.at(-1)).toBe('a/theme15');
    });
});
