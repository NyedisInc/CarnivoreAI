import type { Census, CensusRow } from '../skills-page/skills-types';

export const HIGHLIGHT_ROWS = 5;

type Measured = CensusRow & { readonly fires: NonNullable<CensusRow['fires']> };

function measured(row: CensusRow): row is Measured {
    return row.fires !== null;
}

export function topFired(census: Census | null, window: 'd30' | 'd90'): readonly Measured[] {
    if (!census || census.state !== 'measured') return [];
    return census.skills
        .filter(measured)
        .filter((row) => row.fires[window] > 0)
        .sort((a, b) => b.fires[window] - a.fires[window] || a.name.localeCompare(b.name))
        .slice(0, HIGHLIGHT_ROWS);
}
