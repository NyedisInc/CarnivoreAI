import { describe, expect, test } from 'vitest';

import { cardViews } from '../catalog/card';
import { newestItems } from '../catalog/census';
import { groupInstalled } from '../catalog/installed-rows';
import type { CatalogItem, InstalledItem } from '../catalog/types';
import { applyKey, censusOf, listFor, searchQuery, START, type Source } from './query';

const item = (id: string, kind: string, title: string, brief: string, first: string): CatalogItem =>
    ({ id, name: id.split('/')[1], kind, publisher: id.split('/')[0], latest: '1.0', first_published_at: first, card: { title, brief }, versions: [{ v: '1.0', published_at: first }] }) as unknown as CatalogItem;

const ITEMS: CatalogItem[] = [
    item('acme/deploy', 'skill', 'Deploy Runner', 'ship it', '2026-10-01T00:00:00Z'),
    item('acme/lint', 'skill', 'Lint Fixer', 'tidy code', '2026-10-05T00:00:00Z'),
    item('zoe/dusk', 'theme', 'Dusk', 'warm dark', '2026-09-01T00:00:00Z'),
    item('zoe/neon', 'theme', 'Neon', 'xenon glow', '2026-10-10T00:00:00Z'),
    item('kim/hook', 'mod', 'Hook Pack', 'git hooks', '2026-10-12T00:00:00Z'),
    item('kim/xray', 'plugin', 'Xray', 'inspect panes', '2026-10-14T00:00:00Z'),
    item('lee/xcode', 'skill', 'Xcode Helper', 'build apps', '2026-10-16T00:00:00Z'),
];
const row = (id: string, update = false): InstalledItem => ({ install_id: `i-${id}`, item_id: id, scope: 'global', update_available: update }) as InstalledItem;
const LEDGER = [row('acme/deploy'), row('acme/lint', true), row('zoe/dusk'), row('lee/xcode')];
const COUNTS = new Map<string, number>([['acme/deploy', 40], ['acme/lint', 90], ['zoe/dusk', 15], ['zoe/neon', 200], ['kim/xray', 5], ['lee/xcode', 7]]);

function sourceOf(items: CatalogItem[], ledger: InstalledItem[], installs: Map<string, number>): Source {
    return { cards: cardViews(items, false), items, installed: groupInstalled(ledger), installs, fresh: new Set(newestItems(items, 5).map((i) => String(i.id))) };
}
const ids = (src: Source, q = START): (string | null)[] => listFor(src, q).map((c) => c.id);

describe('Elite Access file area query', () => {
    const src = sourceOf(ITEMS, LEDGER, COUNTS);

    test('i then d lists only installed items, most downloaded first', () => {
        const installed = applyKey(START, 'i')!;
        const sorted = applyKey(installed, 'd')!;
        expect(sorted.state).toBe('installed');
        expect(sorted.sort).toBe('downloaded');
        expect(ids(src, sorted)).toEqual(['acme/lint', 'acme/deploy', 'zoe/dusk', 'lee/xcode']);
        expect(ids(src, applyKey(sorted, 'i')!)).toHaveLength(ITEMS.length);
    });

    test('l lists the 10 highest measured counts and leaves an unmeasured item out', () => {
        const bulk = Array.from({ length: 12 }, (_, i) => item(`bulk/b${i}`, 'skill', `B${i}`, 'filler', `2026-08-${String(i + 1).padStart(2, '0')}T00:00:00Z`));
        const counts = new Map<string, number>(bulk.map((b, i) => [String(b.id), 100 + i]));
        const items = [...bulk, item('bulk/unmeasured', 'skill', 'Unmeasured', 'no count', '2026-10-17T00:00:00Z')];
        const top = ids(sourceOf(items, [], counts), applyKey(START, 'l')!);
        expect(top).toHaveLength(10);
        expect(top).toEqual(Array.from({ length: 10 }, (_, i) => `bulk/b${11 - i}`));
        expect(top).not.toContain('bulk/unmeasured');
        expect(ids(src, applyKey(START, 'l')!)).not.toContain('kim/hook');
        expect(applyKey(applyKey(START, 'l')!, 'l')).toEqual(START);
    });

    test('s with a search x gives the counts the FILES and STATE panels show', () => {
        const q = { ...applyKey(START, 's')!, q: 'x' };
        const c = censusOf(src, q);
        expect(c.total).toBe(ITEMS.length);
        expect(c.files).toEqual({ a: 4, s: 2, t: 1, m: 0, p: 1 });
        expect(c.state).toEqual({ i: 2, v: 0, u: 1, n: 2 });
        for (const [key, n] of Object.entries(c.files)) expect(ids(src, { ...applyKey(q, key)!, q: 'x' })).toHaveLength(n);
        expect(ids(src, q)).toEqual(['lee/xcode', 'acme/lint']);
        expect(searchQuery(q, '/x')).toMatchObject({ kind: 'all', state: 'any', q: 'x', sort: q.sort });
    });
});
