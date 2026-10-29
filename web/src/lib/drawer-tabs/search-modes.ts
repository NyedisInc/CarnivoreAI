import { contextProvider, groupedProvider } from '../deepsearch/providers';
import type { DrawerSearchProvider } from '../deepsearch/provider-types';

export const PROMPTS_SEARCH_PATH = '/pipeline/prompts/search';

export const MODE_NAMES = 'names';
export const MODE_PROMPTS = 'prompts';
export const MODE_ALL = 'all';
export const LEGACY_GREP_MODE = 'grep';
export const CONTEXT_MODE_ID = 'deepsearch-database';

export interface SearchModeDef {
    readonly id: string;
    readonly icon: string;
    readonly nameKey: string;
    readonly placeholderKey: string;
    readonly labelKey: string;
    readonly provider: DrawerSearchProvider | null;
}

function promptsProvider(): DrawerSearchProvider {
    return groupedProvider({
        path: PROMPTS_SEARCH_PATH,
        placeholderKey: 'drawer.search.mode.prompts_placeholder',
        labelKey: 'drawer.search.mode.prompts_label',
        noMatchesKey: 'drawer.search.mode.prompts_no_matches',
        promptStyle: true,
    });
}

export const CORE_MODES: readonly SearchModeDef[] = [
    {
        id: MODE_NAMES,
        icon: 'bot',
        nameKey: 'drawer.search.mode.names',
        placeholderKey: 'drawer.search.placeholder',
        labelKey: 'drawer.search.label',
        provider: null,
    },
    {
        id: MODE_PROMPTS,
        icon: 'prompt',
        nameKey: 'drawer.search.mode.prompts',
        placeholderKey: 'drawer.search.mode.prompts_placeholder',
        labelKey: 'drawer.search.mode.prompts_label',
        get provider(): DrawerSearchProvider {
            return promptsProvider();
        },
    },
    {
        id: CONTEXT_MODE_ID,
        icon: 'deep-search',
        nameKey: 'drawer.search.mode.context',
        placeholderKey: 'deepsearch.placeholder',
        labelKey: 'deepsearch.label',
        get provider(): DrawerSearchProvider {
            return contextProvider();
        },
    },
    {
        id: MODE_ALL,
        icon: 'search',
        nameKey: 'drawer.search.mode.all',
        placeholderKey: 'drawer.search.mode.all_placeholder',
        labelKey: 'drawer.search.mode.all_label',
        provider: null,
    },
];

export function availableModes(): SearchModeDef[] {
    return [...CORE_MODES];
}

export function knownModeIds(): string[] {
    return [...CORE_MODES.map((m) => m.id), LEGACY_GREP_MODE];
}

export function activeMode(modes: readonly SearchModeDef[], chosen: string): SearchModeDef {
    const id = chosen === LEGACY_GREP_MODE ? CONTEXT_MODE_ID : chosen;
    return modes.find((m) => m.id === id) ?? CORE_MODES[0]!;
}
