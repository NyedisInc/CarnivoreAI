
import { readMigrating, writeMigrating } from '../browser-storage-migrate';

function canWarn(): boolean {
    return typeof console !== 'undefined' && typeof console.warn === 'function';
}

export const ARCHIVED_SESSIONS_VISIBLE_KEY = 'carnivore.launchpad.deletedSessionsVisible';

export const ARCHIVED_PROJECTS_VISIBLE_KEY = 'carnivore.launchpad.archivedVisible';

export type SearchDirection = 'bottom_up' | 'top_down';

export const SEARCH_DIRECTION_KEY = 'carnivore.terminal.searchDirection';

export const SEARCH_DIRECTION_DEFAULT: SearchDirection = 'bottom_up';

const SEARCH_DIRECTIONS: readonly SearchDirection[] = ['bottom_up', 'top_down'];

export const SEARCH_PROMPTS_ONLY_KEY = 'carnivore.terminal.searchPromptsOnly';

export function readChoice<T extends string>(
    key: string,
    allowed: readonly T[],
    fallback: T,
): T {
    let stored: string | null = null;
    try {
        stored = readMigrating(key);
    } catch (err) {
        if (canWarn()) console.warn('CloudeWeb: failed to read the preference', key, err);
        return fallback;
    }
    const hit = allowed.find((value) => value === stored);
    return hit === undefined ? fallback : hit;
}

export function writeChoice(key: string, value: string): void {
    try {
        writeMigrating(key, value);
    } catch (err) {
        if (canWarn()) console.warn('CloudeWeb: failed to persist the preference', key, err);
    }
}

export function readFlag(key: string): boolean {
    try {
        return readMigrating(key) === '1';
    } catch (err) {
        if (canWarn()) console.warn('CloudeWeb: failed to read the preference', key, err);
        return false;
    }
}

export function writeFlag(key: string, on: boolean): void {
    try {
        writeMigrating(key, on ? '1' : '0');
    } catch (err) {
        if (canWarn()) console.warn('CloudeWeb: failed to persist the preference', key, err);
    }
}

let archivedSessionsVisible = $state<boolean | null>(null);

let archivedProjectsVisible = $state<boolean | null>(null);

let searchDirection: SearchDirection | null = null;

let searchDirectionVersion = $state(0);

let searchPromptsOnly: boolean | null = null;

let searchPromptsOnlyVersion = $state(0);

function resolveArchivedSessionsVisible(): boolean {
    if (archivedSessionsVisible === null) {
        archivedSessionsVisible = readFlag(ARCHIVED_SESSIONS_VISIBLE_KEY);
    }
    return archivedSessionsVisible;
}

function resolveArchivedProjectsVisible(): boolean {
    if (archivedProjectsVisible === null) {
        archivedProjectsVisible = readFlag(ARCHIVED_PROJECTS_VISIBLE_KEY);
    }
    return archivedProjectsVisible;
}

function resolveSearchDirection(): SearchDirection {
    if (searchDirection === null) {
        searchDirection = readChoice(
            SEARCH_DIRECTION_KEY,
            SEARCH_DIRECTIONS,
            SEARCH_DIRECTION_DEFAULT,
        );
    }
    return searchDirection;
}

/* the prompts-only toggle */
function resolveSearchPromptsOnly(): boolean {
    if (searchPromptsOnly === null) {
        searchPromptsOnly = readFlag(SEARCH_PROMPTS_ONLY_KEY);
    }
    return searchPromptsOnly;
}

export const uiPrefs = {
    get archivedSessionsVisible(): boolean {
        return resolveArchivedSessionsVisible();
    },

    setArchivedSessionsVisible(on: boolean): void {
        archivedSessionsVisible = !!on;
        writeFlag(ARCHIVED_SESSIONS_VISIBLE_KEY, archivedSessionsVisible);
    },

    get archivedProjectsVisible(): boolean {
        return resolveArchivedProjectsVisible();
    },

    setArchivedProjectsVisible(on: boolean): void {
        archivedProjectsVisible = !!on;
        writeFlag(ARCHIVED_PROJECTS_VISIBLE_KEY, archivedProjectsVisible);
    },

    get searchDirection(): SearchDirection {
        void searchDirectionVersion;
        return resolveSearchDirection();
    },

    setSearchDirection(next: SearchDirection): void {
        searchDirection = next;
        searchDirectionVersion += 1;
        writeChoice(SEARCH_DIRECTION_KEY, next);
    },

    get searchPromptsOnly(): boolean {
        void searchPromptsOnlyVersion;
        return resolveSearchPromptsOnly();
    },

    /* the prompts-only toggle */
    setSearchPromptsOnly(on: boolean): void {
        searchPromptsOnly = !!on;
        searchPromptsOnlyVersion += 1;
        writeFlag(SEARCH_PROMPTS_ONLY_KEY, searchPromptsOnly);
    },

    reload(): void {
        archivedSessionsVisible = readFlag(ARCHIVED_SESSIONS_VISIBLE_KEY);
        archivedProjectsVisible = readFlag(ARCHIVED_PROJECTS_VISIBLE_KEY);
        searchDirection = readChoice(
            SEARCH_DIRECTION_KEY,
            SEARCH_DIRECTIONS,
            SEARCH_DIRECTION_DEFAULT,
        );
        searchDirectionVersion += 1;
        searchPromptsOnly = readFlag(SEARCH_PROMPTS_ONLY_KEY);
        searchPromptsOnlyVersion += 1;
    },

    resetForTests(): void {
        archivedSessionsVisible = null;
        archivedProjectsVisible = null;
        searchDirection = null;
        searchDirectionVersion += 1;
        searchPromptsOnly = null;
        searchPromptsOnlyVersion += 1;
    },
};
