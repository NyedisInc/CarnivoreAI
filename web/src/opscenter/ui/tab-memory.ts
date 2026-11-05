
import { readChoice, writeChoice } from './stored-choice';

const KEY_PREFIX = 'carnivore.tabs.';

export function readTab<T extends string>(pageKey: string, ids: readonly T[], fallback: T): T {
    return readChoice(KEY_PREFIX + pageKey, ids, fallback);
}

export function writeTab(pageKey: string, id: string): void {
    writeChoice(KEY_PREFIX + pageKey, id);
}
