
export const VIEWS = ['list', 'pivot', 'timeline'] as const;
export type SessionsView = (typeof VIEWS)[number];

const KEY = 'carnivore.sessions-page.view';

export function readView(): SessionsView {
    try {
        const v = globalThis.localStorage?.getItem(KEY);
        return (VIEWS as readonly string[]).includes(v ?? '') ? (v as SessionsView) : 'list';
    } catch {
        return 'list';
    }
}

export function writeView(view: SessionsView): void {
    try {
        globalThis.localStorage?.setItem(KEY, view);
    } catch {
    }
}
