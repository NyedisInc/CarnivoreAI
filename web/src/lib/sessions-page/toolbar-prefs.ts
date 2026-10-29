
export const PROJECT_SORTS = ['default', 'name', 'recent'] as const;
export type ProjectSortKey = (typeof PROJECT_SORTS)[number];

const HIDDEN_KEY = 'carnivore.sessions-page.show-hidden';
const SORT_KEY = 'carnivore.sessions-page.project-sort';

export function readShowHidden(): boolean {
    try {
        return globalThis.localStorage?.getItem(HIDDEN_KEY) === '1';
    } catch {
        return false;
    }
}

export function writeShowHidden(on: boolean): void {
    try {
        globalThis.localStorage?.setItem(HIDDEN_KEY, on ? '1' : '0');
    } catch {
    }
}

export function readProjectSort(): ProjectSortKey {
    try {
        const v = globalThis.localStorage?.getItem(SORT_KEY) ?? '';
        return (PROJECT_SORTS as readonly string[]).includes(v) ? (v as ProjectSortKey) : 'default';
    } catch {
        return 'default';
    }
}

export function writeProjectSort(key: ProjectSortKey): void {
    try {
        globalThis.localStorage?.setItem(SORT_KEY, key);
    } catch {
    }
}
