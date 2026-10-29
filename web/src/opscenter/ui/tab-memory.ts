
const KEY_PREFIX = 'carnivore.tabs.';

export function readTab(pageKey: string, ids: readonly string[], fallback: string): string {
    try {
        const stored = globalThis.localStorage?.getItem(KEY_PREFIX + pageKey);
        return stored !== null && stored !== undefined && ids.includes(stored) ? stored : fallback;
    } catch {
        return fallback;
    }
}

export function writeTab(pageKey: string, id: string): void {
    try {
        globalThis.localStorage?.setItem(KEY_PREFIX + pageKey, id);
    } catch {
    }
}
