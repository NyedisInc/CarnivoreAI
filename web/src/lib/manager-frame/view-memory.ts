
export type ManagerView = 'grid' | 'list';

const KEY_PREFIX = 'carnivore.view.';

export function readView(pageKey: string, fallback: ManagerView): ManagerView {
    try {
        const stored = globalThis.localStorage?.getItem(KEY_PREFIX + pageKey);
        return stored === 'grid' || stored === 'list' ? stored : fallback;
    } catch {
        return fallback;
    }
}

export function writeView(pageKey: string, view: ManagerView): void {
    try {
        globalThis.localStorage?.setItem(KEY_PREFIX + pageKey, view);
    } catch {
    }
}
