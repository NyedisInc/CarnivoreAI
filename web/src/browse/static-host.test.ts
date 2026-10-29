import { describe, expect, it, vi } from 'vitest';
import fixture from './fixtures/index.fixture.json';
import palettesFixture from './fixtures/theme-palettes.fixture.json';
import { palettesFrom } from '../lib/catalog/theme-palettes';
import { PALETTES_URL, INDEX_URL, firstPublishedAt, keyIdOfSignature, listFromIndex, staticCatalogHost } from './static-host';
import { catalogMediaUrl } from './card-media-static';

function fakeFetch(palettes: Response | null = null) {
    const asked: string[] = [];
    const fn = vi.fn(async (url: RequestInfo | URL) => {
        asked.push(String(url));
        if (String(url) === INDEX_URL) return new Response(JSON.stringify(fixture), { status: 200 });
        if (String(url) === PALETTES_URL && palettes) return palettes;
        return new Response('', { status: 404 });
    });
    return { fn: fn as unknown as typeof fetch, asked };
}

describe('staticCatalogHost', () => {
    it('lists every kind with the app shape and no server fields', async () => {
        const { fn } = fakeFetch();
        const res = await staticCatalogHost(fn).listItems();
        const kinds = new Set((res.items ?? []).map((i) => i.kind));
        for (const k of ['theme', 'skill', 'cplug', 'mod', 'plugin']) expect(kinds.has(k)).toBe(true);
        expect(res.untrusted).toEqual([]);
        for (const item of res.items ?? []) {
            expect(item.installed).toBeNull();
            expect(item.untrusted).toBe(false);
            expect(typeof item.id).toBe('string');
            expect(item.versions?.length).toBeGreaterThan(0);
        }
        expect(res.index?.serial).toBe(fixture.serial);
        expect(res.index?.generated_at).toBe(fixture.generated_at);
        expect(res.index?.degraded).toBe(false);
    });

    it('ranks featured items and stamps first_published_at as the oldest version', () => {
        const doc = {
            serial: 1,
            expires_at: '2026-01-02T00:00:00Z',
            featured: ['a/b'],
            items: [
                { id: 'a/b', versions: [{ published_at: '2026-03-01T00:00:00Z' }, { published_at: '2026-02-01T00:00:00+01:00' }] },
                { id: 'c/d', versions: [] },
            ],
        };
        const res = listFromIndex(doc as never, Date.parse('2026-06-01T00:00:00Z'));
        expect(res.items![0]!.featured_rank).toBe(0);
        expect(res.items![0]!.first_published_at).toBe('2026-02-01T00:00:00+01:00');
        expect(res.items![1]!.featured_rank).toBeNull();
        expect(res.items![1]!.first_published_at).toBeNull();
        expect(res.index?.degraded).toBe(true);
        expect(firstPublishedAt([])).toBeNull();
    });

    it('answers a hero as a plain same-origin url', async () => {
        const sha = 'ab'.repeat(32);
        expect(await catalogMediaUrl(sha)).toBe(`v1/media/${sha}.webp`);
    });

    it('gives no palettes on a 404 or a bad file, and reads a good one', async () => {
        expect(await staticCatalogHost(fakeFetch().fn).themePalettes!()).toEqual({ items: {}, pending: [] });
        const bad = fakeFetch(new Response('not json', { status: 200 }));
        expect(await staticCatalogHost(bad.fn).themePalettes!()).toEqual({ items: {}, pending: [] });
        const good = fakeFetch(new Response(JSON.stringify({ items: { 'x/y': { digest: 'd' } }, pending: ['z'] }), { status: 200 }));
        const got = await staticCatalogHost(good.fn).themePalettes!();
        expect(Object.keys(got.items)).toEqual(['x/y']);
        expect(got.pending).toEqual(['z']);
    });

    it('needs no server: empty answers, refused writes, and no fetch beyond v1/', async () => {
        const { fn, asked } = fakeFetch();
        const host = staticCatalogHost(fn);
        await host.listItems();
        await host.themePalettes!();
        expect(await host.listInstalled()).toEqual({ items: [] });
        expect(await host.installCounts(['a'])).toEqual({ items: {} });
        expect((await host.itemRatings('a')).count).toBe(0);
        expect(await host.catalogSession()).toEqual({ signed_in: false });
        expect(host.runningSessions()).toEqual([]);
        await expect(host.install({} as never)).rejects.toThrow('read only');
        expect(asked.length).toBeGreaterThan(0);
        for (const url of asked) expect(url.startsWith('v1/')).toBe(true);
    });

    it('finds one item for the reading pane', async () => {
        const host = staticCatalogHost(fakeFetch().fn);
        const first = (await host.listItems()).items![0]!;
        expect((await host.item(first.id!))?.id).toBe(first.id);
        expect(await host.item('nope/none')).toBeNull();
    });

    it('reads the palettes file S3 bakes (the app route shape) into real theme palettes', async () => {
        const body = new Response(JSON.stringify(palettesFixture), { status: 200 });
        const got = await staticCatalogHost(fakeFetch(body).fn).themePalettes!();
        const palettes = palettesFrom(got);
        expect([...palettes.keys()].sort()).toEqual(['carnivore/calming', 'carnivore/gameboy']);
        expect(palettes.get('carnivore/calming')?.accent).toMatch(/^#/);
    });

    it('names the signing key the way minisign prints it, and nothing for a bad file', () => {
        const sig = 'untrusted comment: x\nRUToHYwCxY1tHoRbrhxFfYxzu5ykwie80b7tPiV9H4qARZ3pYk8g4AIeEPg1iJl2t0JZLgkAcPPz2JIZd/KSJyvkMV7Vz6mwQA4=\n';
        expect(keyIdOfSignature(sig)).toBe('1E6D8DC5028C1DE8');
        expect(keyIdOfSignature('')).toBeNull();
        expect(keyIdOfSignature('x\n!!!')).toBeNull();
    });
});
