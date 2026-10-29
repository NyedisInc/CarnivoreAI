
export type PageView = 'ledger' | 'cards';

const KEY_PREFIX = 'carnivore.pageview.';

export function readPageView(pageKey: string, fallback: PageView): PageView {
    try {
        const stored = globalThis.localStorage?.getItem(KEY_PREFIX + pageKey);
        return stored === 'ledger' || stored === 'cards' ? stored : fallback;
    } catch {
        return fallback;
    }
}

export function writePageView(pageKey: string, view: PageView): void {
    try {
        globalThis.localStorage?.setItem(KEY_PREFIX + pageKey, view);
    } catch {
    }
}
