/* and writes nothing */
import { LAYOUT_ITEM_FOLD_PREFIX, isSpawnedFoldKey } from './store-keys';

export function isInvertedFoldKey(key: string): boolean {
    return key.indexOf(LAYOUT_ITEM_FOLD_PREFIX) === 0 || isSpawnedFoldKey(key);
}

export function foldPresent(key: string, storedFolded: boolean, filtering: boolean): boolean {
    if (!filtering) return storedFolded;
    return isInvertedFoldKey(key);
}
