import { describe, expect, it } from 'vitest';
import type { FeatureCatalogItem } from './features-by-area';
import type { FeatureChangeLine, FeatureRelease } from './features-grouping';
import { parseQuery } from './fuzzy-search';
import { matchReleases } from './releases-search';

function line(summary: string, extra: Partial<FeatureChangeLine> = {}): FeatureChangeLine {
    return {
        summary, details: null, type: 'added', date: '2026-09-01', featureNames: [],
        featureLinks: [], pr: null, issue: null, breaking: false, ...extra,
    };
}

function release(name: string, ...rows: FeatureChangeLine[]): FeatureRelease {
    return { name, isUnreleased: false, date: null, types: [{ type: 'added', changes: rows }] };
}

const releases = [
    release('v1.2.0', line('the update icon shifts when shift is held'), line('unrelated row')),
    release('v1.1.0', line('nothing here')),
    release('v1.0.0', line('macOS keychain read', { featureLinks: [{ id: 'kc', name: 'Keychain' }], featureNames: ['Keychain'] })),
];
const catalog: Record<string, FeatureCatalogItem> = {
    kc: { id: 'kc', name: 'Keychain', summary: 's', area: 'a', status: 'x', how_to: ['open the vault panel'] },
};

describe('matchReleases', () => {
    it('keeps matches under their release, in the given order, and hides releases with none', () => {
        const out = matchReleases(releases, parseQuery('keychan shift'), catalog);
        expect(out).toEqual([]);
        const shift = matchReleases(releases, parseQuery('shift update'), catalog);
        expect(shift.map((m) => m.release.name)).toEqual(['v1.2.0']);
        expect(shift[0]!.rows.map((r) => r.index)).toEqual([0]);
        const both = matchReleases(releases, parseQuery('keychan'), catalog);
        expect(both.map((m) => m.release.name)).toEqual(['v1.0.0']);
    });
    it('searches a linked feature body and flags the row body-only', () => {
        const out = matchReleases(releases, parseQuery('vault'), catalog);
        expect(out[0]!.rows[0]).toMatchObject({ index: 0, bodyOnly: true });
    });
    it('a row matched by its own words is not body-only', () => {
        expect(matchReleases(releases, parseQuery('keychain'), catalog)[0]!.rows[0]!.bodyOnly).toBe(false);
    });
    it('returns nothing for an empty query', () => {
        expect(matchReleases(releases, [], catalog)).toEqual([]);
    });
});

describe('matchReleases modes', () => {
    const paced = [
        release('v2.0.0', line('the pace marker is vertical'), line('the page footer moved'), line('a place for it')),
    ];
    it('plain mode ("pace") keeps only rows containing "pace"', () => {
        const out = matchReleases(paced, parseQuery('pace'), {}, 'plain');
        expect(out[0]!.rows.map((r) => r.index)).toEqual([0]);
    });
    it('fuzzy mode ("pace") also keeps the one-edit neighbours page and place', () => {
        const out = matchReleases(paced, parseQuery('pace'), {}, 'fuzzy');
        expect(out[0]!.rows.map((r) => r.index)).toEqual([0, 1, 2]);
    });
});

