import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { cardViews } from './card';
import { kindCounts } from './census';
import { kindsOf } from './filter';
import { kindChipsFor } from './filter-groups';
import { countByDisplayKind, displayKind } from './kind-display';
import type { CatalogItem } from './types';

const item = (id: string, kind: string): CatalogItem => ({ id, name: id.split('/')[1], kind, latest: '1.0.0' }) as unknown as CatalogItem;
const ITEMS = [item('external/rea', 'plugin'), item('carnivore/mcphealth', 'cplug'), item('external/cleanyourtv', 'cplug'), item('a/skill', 'skill')];

describe('displayKind', () => {
    test('folds cplug into plugin and leaves every other kind alone', () => {
        expect(displayKind('cplug')).toBe('plugin');
        expect(displayKind('plugin')).toBe('plugin');
        expect(displayKind('theme')).toBe('theme');
        expect(displayKind(null)).toBeNull();
    });
    test('the census counts plugin and cplug as one plugins entry', () => {
        expect(kindCounts(ITEMS)).toEqual([{ kind: 'skill', count: 1 }, { kind: 'plugin', count: 3 }]);
    });
    test('the store menu counts plugin and cplug as one plugins entry', () => {
        expect(countByDisplayKind(ITEMS, ['skill', 'plugin'])).toEqual({ skill: 1, plugin: 3 });
    });
    test('cards carry the folded kind, keep the index kind, and the chips offer one plugins entry', () => {
        const cards = cardViews(ITEMS, false);
        expect(cards.filter((c) => c.kind === 'plugin')).toHaveLength(3);
        expect(cards.find((c) => c.id === 'carnivore/mcphealth')).toMatchObject({ kind: 'plugin', indexKind: 'cplug', isCplug: true, isPlugin: false });
        expect(kindsOf(cards)).toEqual(['plugin', 'skill']);
        const chips = kindChipsFor(kindsOf(cards), null, (k: string) => k);
        expect(chips.filter((c) => c.kind === 'plugin')).toHaveLength(1);
        expect(chips.some((c) => c.kind === 'cplug')).toBe(false);
    });
});

describe('the string catalog', () => {
    test('no user-visible value says cplug', () => {
        const bad = Object.entries(enCatalog as unknown as Record<string, unknown>).filter(([, v]) => typeof v === 'string' && /cplug/i.test(v)).map(([k]) => k);
        expect(bad).toEqual([]);
    });
});
