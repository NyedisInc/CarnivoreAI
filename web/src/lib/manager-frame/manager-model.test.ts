import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { groupItems, isNarrowed, isSwitchable, MANAGER_KEYS, matchesQuery, visibleItems } from './manager-model';
import type { ManagerFilter, ManagerItem } from './types';

const ITEMS: [ManagerItem, ManagerItem, ManagerItem] = [
    { id: 'a', name: 'git tools', brief: 'commit helpers', meta: '1.2.0', marks: ['builtin'], enabled: true },
    { id: 'b', name: 'music', brief: 'tag an audio library', meta: 'nyedis', enabled: false },
    { id: 'c', name: 'notes', enabled: null },
];

const builtin: ManagerFilter = {
    id: 'builtin',
    label: 'builtin',
    on: true,
    test: (item) => (item.marks ?? []).includes('builtin'),
};

describe('matchesQuery', () => {
    test('an empty or blank search matches everything', () => {
        expect(ITEMS.every((item) => matchesQuery(item, '   '))).toBe(true);
    });

    test('matches case-insensitively over name, brief, meta and marks', () => {
        expect(matchesQuery(ITEMS[0], 'GIT')).toBe(true);
        expect(matchesQuery(ITEMS[0], 'helpers')).toBe(true);
        expect(matchesQuery(ITEMS[0], '1.2')).toBe(true);
        expect(matchesQuery(ITEMS[0], 'builtin')).toBe(true);
        expect(matchesQuery(ITEMS[1], 'nyedis')).toBe(true);
    });

    test('every term must match: two terms narrow, never widen', () => {
        expect(matchesQuery(ITEMS[0], 'git commit')).toBe(true);
        expect(matchesQuery(ITEMS[0], 'git audio')).toBe(false);
    });
});

describe('visibleItems', () => {
    test('keeps the page order and applies search AND pressed chips', () => {
        expect(visibleItems(ITEMS, '', []).map((i) => i.id)).toEqual(['a', 'b', 'c']);
        expect(visibleItems(ITEMS, '', [builtin]).map((i) => i.id)).toEqual(['a']);
        expect(visibleItems(ITEMS, 'music', [builtin])).toEqual([]);
    });

    test('an unpressed chip filters nothing', () => {
        expect(visibleItems(ITEMS, '', [{ ...builtin, on: false }])).toHaveLength(3);
    });
});

describe('isNarrowed', () => {
    test('true for a search or a pressed chip, false otherwise', () => {
        expect(isNarrowed('', [])).toBe(false);
        expect(isNarrowed(' ', [{ ...builtin, on: false }])).toBe(false);
        expect(isNarrowed('x', [])).toBe(true);
        expect(isNarrowed('', [builtin])).toBe(true);
    });
});

describe('isSwitchable', () => {
    test('only a measured boolean with a wired handler draws a switch', () => {
        expect(isSwitchable(ITEMS[0], true)).toBe(true);
        expect(isSwitchable(ITEMS[1], true)).toBe(true);
        expect(isSwitchable(ITEMS[2], true)).toBe(false);
        expect(isSwitchable(ITEMS[0], false)).toBe(false);
    });
});

describe('MANAGER_KEYS', () => {
    test('every key the frame reads is in the catalog', () => {
        const catalog = enCatalog as Record<string, unknown>;
        const missing = Object.values(MANAGER_KEYS).filter((key) => !(key in catalog));
        expect(missing).toEqual([]);
    });
});

describe('groupItems', () => {
    const by = (item: ManagerItem): string => (item.id === 'c' ? 'x' : 'y');

    test('follows the page order, keeps an empty group when not narrowed, appends a group only in the data', () => {
        const groups = groupItems(ITEMS, ['z', 'y'], by, false);
        expect(groups.map((g) => [g.id, g.items.map((i) => i.id)])).toEqual([['z', []], ['y', ['a', 'b']], ['x', ['c']]]);
    });

    test('while narrowed, a group with nothing to show is dropped', () => {
        const groups = groupItems([ITEMS[2]], ['z', 'y'], by, true);
        expect(groups.map((g) => g.id)).toEqual(['x']);
    });
});
