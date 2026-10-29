import type { FeatureCatalogItem } from './features-by-area';
import type { FeatureChangeLine, FeatureRelease } from './features-grouping';
import { scoreTexts, type SearchMode } from './fuzzy-search';

export interface RowMatch {
    row: FeatureChangeLine;
    index: number;
    bodyOnly: boolean;
}

export interface ReleaseMatch {
    release: FeatureRelease;
    rows: RowMatch[];
}

export function rowsOfRelease(release: FeatureRelease): FeatureChangeLine[] {
    return release.types.flatMap((group) => group.changes);
}

function ownTexts(row: FeatureChangeLine): string[] {
    return [row.summary, row.details ?? '', ...row.featureNames];
}

function bodyTexts(row: FeatureChangeLine, catalogById: Readonly<Record<string, FeatureCatalogItem>>): string[] {
    return row.featureLinks.flatMap((link) => {
        const item = catalogById[link.id];
        return item ? [item.summary, ...(item.where ?? []), ...(item.how_to ?? []), ...(item.examples ?? [])] : [];
    });
}

export function matchReleases(
    releases: readonly FeatureRelease[],
    tokens: readonly string[],
    catalogById: Readonly<Record<string, FeatureCatalogItem>>,
    mode: SearchMode = 'fuzzy',
): ReleaseMatch[] {
    if (tokens.length === 0) return [];
    const out: ReleaseMatch[] = [];
    for (const release of releases) {
        const rows: RowMatch[] = [];
        rowsOfRelease(release).forEach((row, index) => {
            const own = ownTexts(row);
            if (scoreTexts(tokens, own, mode) > 0) {
                rows.push({ row, index, bodyOnly: false });
            } else if (scoreTexts(tokens, [...own, ...bodyTexts(row, catalogById)], mode) > 0) {
                rows.push({ row, index, bodyOnly: true });
            }
        });
        if (rows.length > 0) out.push({ release, rows });
    }
    return out;
}
