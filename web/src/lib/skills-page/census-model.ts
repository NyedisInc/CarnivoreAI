import type { CensusRow } from './skills-types';

export type CensusSortKey = 'name' | 'tokens' | 'd7' | 'd30' | 'd90';

function valueOf(row: CensusRow, key: Exclude<CensusSortKey, 'name'>): number | null {
    if (key === 'tokens') return row.tokens_est;
    return row.fires === null ? null : row.fires[key];
}

export function sortCensus(rows: readonly CensusRow[], query: string, key: CensusSortKey, dir: 'asc' | 'desc'): CensusRow[] {
    const needle = query.trim().toLowerCase();
    const sign = dir === 'asc' ? 1 : -1;
    return rows
        .filter((row) => needle === '' || row.name.toLowerCase().includes(needle))
        .sort((a, b) => {
            if (key === 'name') return sign * a.name.localeCompare(b.name);
            const x = valueOf(a, key);
            const y = valueOf(b, key);
            if (x === null && y === null) return a.name.localeCompare(b.name);
            if (x === null) return 1;
            if (y === null) return -1;
            return x === y ? a.name.localeCompare(b.name) : sign * (x - y);
        });
}
