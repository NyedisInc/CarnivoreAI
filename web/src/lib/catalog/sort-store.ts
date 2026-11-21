import { VISIBLE_SORT_KEYS, type SortKey } from './sort';

const SORT_STORE_KEY = 'carnivore.warez.sort';

export function readSort(): SortKey {
    try {
        const stored = globalThis.localStorage?.getItem(SORT_STORE_KEY) ?? '';
        return (VISIBLE_SORT_KEYS as readonly string[]).includes(stored) ? (stored as SortKey) : 'featured';
    } catch {
        return 'featured';
    }
}

export function writeSort(next: SortKey): void {
    try {
        globalThis.localStorage?.setItem(SORT_STORE_KEY, next);
    } catch {
    }
}
