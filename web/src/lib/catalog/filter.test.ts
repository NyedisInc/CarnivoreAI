import { describe, expect, test } from 'vitest';

import { cardViews, type CardView } from './card';
import {
    MAX_TAG_CHIPS,
    NO_FILTERS,
    isNarrowed,
    kindsOf,
    matchesQuery,
    publishersOf,
    tagsOf,
    updateCount,
    visibleCards,
} from './filter';
import { sortCards } from './sort';
import type { CatalogItem, InstalledItem } from './types';

const ITEMS: CatalogItem[] = [
    {
        id: 'acme/deploy',
        name: 'deploy',
        publisher: 'acme',
        latest: '1.0',
        card: { title: 'Deploy Runner', brief: 'ships a build to a test machine', tags: ['cli', 'ops'] },
        versions: [{ v: '1.0', scripts: 2 }],
    },
    {
        id: 'acme/notes',
        name: 'notes',
        publisher: 'acme',
        latest: '2.0',
        card: { title: 'Note Taker', brief: 'writes meeting notes', tags: ['writing'] },
        versions: [{ v: '2.0', scripts: 0 }],
    },
    {
        id: 'zoe/audit',
        name: 'audit',
        publisher: 'zoe',
        latest: '3.1',
        card: { title: 'Security Audit', brief: 'reviews a repo', tags: ['ops', 'security'] },
        versions: [{ v: '3.1' }],
    },
];

const CARDS: CardView[] = cardViews(ITEMS, false);

const LEDGER: Record<string, InstalledItem[]> = {
    'acme/deploy': [{
        install_id: 'i1',
        item_id: 'acme/deploy',
        scope: 'global',
        revision: 4,
        update_available: true,
    }],
};

function ids(cards: readonly CardView[]): string[] {
    return cards.map((card) => card.id ?? '');
}

describe('the search box', () => {
    test('an empty query narrows nothing', () => {
        expect(ids(visibleCards(CARDS, NO_FILTERS, '', {}))).toEqual([
            'acme/deploy',
            'acme/notes',
            'zoe/audit',
        ]);
    });

    test('it matches the title, the name, the brief, the publisher and a tag', () => {
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'runner', {}))).toEqual(['acme/deploy']);
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'notes', {}))).toEqual(['acme/notes']);
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'repo', {}))).toEqual(['zoe/audit']);
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'zoe', {}))).toEqual(['zoe/audit']);
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'security', {}))).toEqual(['zoe/audit']);
    });

    test('EVERY WORD MUST HIT, and each may hit a different field', () => {
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'acme cli', {}))).toEqual(['acme/deploy']);
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'acme security', {}))).toEqual([]);
    });

    test('it is case insensitive and ignores surrounding space', () => {
        expect(matchesQuery(CARDS[0] as CardView, '  DEPLOY  ')).toBe(true);
    });

    test('NEGATIVE CONTROL: a query that matches nothing returns nothing', () => {
        expect(ids(visibleCards(CARDS, NO_FILTERS, 'xyzzy', {}))).toEqual([]);
    });
});

describe('the four flags', () => {
    test('installed keeps only rows the ledger carries', () => {
        const filters = { ...NO_FILTERS, installed: true };
        expect(ids(visibleCards(CARDS, filters, '', LEDGER))).toEqual(['acme/deploy']);
        expect(ids(visibleCards(CARDS, filters, '', {}))).toEqual([]);
    });

    test('updates reads the ledger badge and nothing else', () => {
        const filters = { ...NO_FILTERS, updates: true };
        expect(ids(visibleCards(CARDS, filters, '', LEDGER))).toEqual(['acme/deploy']);
        const quiet = { 'acme/deploy': [{ ...LEDGER['acme/deploy']![0]!, update_available: false }] };
        expect(ids(visibleCards(CARDS, filters, '', quiet as never))).toEqual([]);
    });

    test('scripts needs a COUNTED, POSITIVE number', () => {
        const filters = { ...NO_FILTERS, scripts: true };
        expect(ids(visibleCards(CARDS, filters, '', {}))).toEqual(['acme/deploy']);
    });

    test('untrusted narrows to the rows out of the untrusted list', () => {
        const filters = { ...NO_FILTERS, untrusted: true };
        expect(ids(visibleCards(CARDS, filters, '', {}))).toEqual([]);
        const untrusted = cardViews([ITEMS[0] as CatalogItem], true);
        expect(ids(visibleCards(untrusted, filters, '', {}))).toEqual(['acme/deploy']);
    });

    test('the flags are AND-ed, never OR-ed', () => {
        const filters = { ...NO_FILTERS, installed: true, scripts: true };
        expect(ids(visibleCards(CARDS, filters, '', LEDGER))).toEqual(['acme/deploy']);
        const both = { ...NO_FILTERS, installed: true, untrusted: true };
        expect(ids(visibleCards(CARDS, both, '', LEDGER))).toEqual([]);
    });
});

describe('the publisher and the tags', () => {
    test('a publisher is matched on the exact string the index spelled', () => {
        const filters = { ...NO_FILTERS, publisher: 'acme' };
        expect(ids(visibleCards(CARDS, filters, '', {}))).toEqual(['acme/deploy', 'acme/notes']);
    });

    test('null is EVERY publisher, which an empty string is not', () => {
        expect(ids(visibleCards(CARDS, NO_FILTERS, '', {}))).toHaveLength(3);
        expect(ids(visibleCards(CARDS, { ...NO_FILTERS, publisher: '' }, '', {}))).toEqual([]);
    });

    test('tags are AND-ed: every one named must be present', () => {
        expect(ids(visibleCards(CARDS, { ...NO_FILTERS, tags: ['ops'] }, '', {}))).toEqual([
            'acme/deploy',
            'zoe/audit',
        ]);
        expect(
            ids(visibleCards(CARDS, { ...NO_FILTERS, tags: ['ops', 'security'] }, '', {})),
        ).toEqual(['zoe/audit']);
    });

    test('the publisher list is de-duplicated and offers only what is there', () => {
        expect(publishersOf(CARDS)).toEqual(['acme', 'zoe']);
    });

    test('the tag vocabulary is de-duplicated and BOUNDED', () => {
        expect(tagsOf(CARDS)).toEqual(['cli', 'ops', 'writing', 'security']);
        const many = cardViews(
            Array.from({ length: 200 }, (_unused, index) => ({
                id: `x/${index}`,
                card: { tags: [`tag-${index}`] },
            })),
            false,
        );
        expect(tagsOf(many)).toHaveLength(MAX_TAG_CHIPS);
    });
});

describe('what tells an empty catalog apart from a narrow filter', () => {
    test('nothing typed and nothing ticked is not narrowed', () => {
        expect(isNarrowed(NO_FILTERS, '')).toBe(false);
        expect(isNarrowed(NO_FILTERS, '   ')).toBe(false);
    });

    test('any one of them is', () => {
        expect(isNarrowed(NO_FILTERS, 'a')).toBe(true);
        expect(isNarrowed({ ...NO_FILTERS, installed: true }, '')).toBe(true);
        expect(isNarrowed({ ...NO_FILTERS, publisher: 'acme' }, '')).toBe(true);
        expect(isNarrowed({ ...NO_FILTERS, tags: ['cli'] }, '')).toBe(true);
    });
});

describe('the update count on the entry point', () => {
    test('only an explicit true is counted', () => {
        expect(
            updateCount([
                { update_available: true },
                { update_available: false },
                { update_available: null },
                {},
            ]),
        ).toBe(1);
    });

    test('an unreadable ledger counts nothing rather than throwing', () => {
        expect(updateCount(null)).toBe(0);
        expect(updateCount(undefined)).toBe(0);
        expect(updateCount('lots' as never)).toBe(0);
    });
});

describe('narrowing to one kind', () => {
    const mixed = cardViews(
        [
            { id: 'a/sme', kind: 'skill', card: { title: 'sme' } },
            { id: 'a/neon', kind: 'theme', card: { title: 'neon' } },
            { id: 'a/toolbelt', kind: 'plugin', card: { title: 'toolbelt' } },
        ] as CatalogItem[],
        false,
    );

    test('null is EVERY kind, which is not the same as an empty string', () => {
        expect(visibleCards(mixed, NO_FILTERS, '', {}).length).toBe(3);
    });

    test('one kind keeps only that kind', () => {
        const shown = visibleCards(mixed, { ...NO_FILTERS, kind: 'theme' }, '', {});
        expect(shown.map((c) => c.id)).toEqual(['a/neon']);
    });

    test('the third kind narrows the same way the other two do', () => {
        const shown = visibleCards(mixed, { ...NO_FILTERS, kind: 'plugin' }, '', {});
        expect(shown.map((c) => c.id)).toEqual(['a/toolbelt']);
    });

    test('a kind nothing carries shows nothing, rather than everything', () => {
        expect(visibleCards(mixed, { ...NO_FILTERS, kind: 'bundle' }, '', {}).length).toBe(0);
    });

    test('a kind filter counts as narrowing', () => {
        expect(isNarrowed({ ...NO_FILTERS, kind: 'theme' }, '')).toBe(true);
        expect(isNarrowed(NO_FILTERS, '')).toBe(false);
    });

    test('kindsOf offers only kinds that have a row behind them', () => {
        expect(kindsOf(mixed)).toEqual(['skill', 'theme', 'plugin']);
    });

    test('kindsOf de-duplicates and skips rows with no kind', () => {
        const rows = cardViews(
            [
                { id: 'a/1', kind: 'theme' },
                { id: 'a/2', kind: 'theme' },
                { id: 'a/3' },
            ] as CatalogItem[],
            false,
        );
        expect(kindsOf(rows)).toEqual(['theme']);
    });
});

describe('warez sorts and the available filter', () => {
    const rows: CatalogItem[] = [
        { id: 'a/one', name: 'one', first_published_at: '2026-03-01T00:00:00Z' },
        { id: 'a/two', name: 'two', featured_rank: 1, first_published_at: '2026-01-01T00:00:00Z' },
        { id: 'a/three', name: 'three' },
        { id: 'a/four', name: 'four', featured_rank: 0, first_published_at: '2026-02-01T00:00:00Z' },
    ];
    const cards = cardViews(rows, false);
    const order = (key: Parameters<typeof sortCards>[1]): string[] =>
        sortCards(cards, key, rows).map((c) => c.id ?? '');

    test('featured puts ranked items first and unranked ones in index order', () => {
        expect(order('featured')).toEqual(['a/four', 'a/two', 'a/one', 'a/three']);
    });

    test('newest and oldest order by first publish and put unknown dates last', () => {
        expect(order('newest')).toEqual(['a/one', 'a/four', 'a/two', 'a/three']);
        expect(order('oldest')).toEqual(['a/two', 'a/four', 'a/one', 'a/three']);
    });

    test('with no ranks at all, featured is the index order', () => {
        const bare: CatalogItem[] = [{ id: 'x/a' }, { id: 'x/b' }, { id: 'x/c' }];
        expect(sortCards(cardViews(bare, false), 'featured', bare).map((c) => c.id)).toEqual(['x/a', 'x/b', 'x/c']);
    });

    test('available hides an item with any installed reference, installed shows only those', () => {
        const ledger: Record<string, InstalledItem[]> = {
            'acme/notes': [{ install_id: 'i2', item_id: 'acme/notes', scope: 'project', revision: 1 }],
        };
        expect(ids(visibleCards(CARDS, { ...NO_FILTERS, available: true }, '', ledger))).toEqual([
            'acme/deploy',
            'zoe/audit',
        ]);
        expect(ids(visibleCards(CARDS, { ...NO_FILTERS, installed: true }, '', ledger))).toEqual(['acme/notes']);
        expect(isNarrowed({ ...NO_FILTERS, available: true }, '')).toBe(true);
    });
});
