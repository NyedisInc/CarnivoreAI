import type { DynamicTabDef } from '../dynamic-tabs/types';


export const DRAWER_TABS = ['menu', 'agents'] as const;
export type DrawerTab = (typeof DRAWER_TABS)[number];

export const DEFAULT_DRAWER_TAB: DrawerTab = 'agents';

export const DRAWER_TABBODY_ID = 'session-sidebar-tabbody';

export const DRAWER_AREA_BAR_ID = 'session-sidebar-area-bar';

export const DRAWER_TAB_STORAGE_KEY = 'carnivore.session.sidebar.tab';

export const DRAWER_STATS_ID = 'session-sidebar-stats';

export const DRAWER_STATS_RATE_KEY = 'carnivore.session.sidebar.statsRate';
export const DRAWER_STATS_WINDOW_KEY = 'carnivore.session.sidebar.statsWindow';

export const DRAWER_LIST_ID = 'session-sidebar-list';

export const DRAWER_SEARCH_ID = 'session-sidebar-search';

export const DRAWER_DEEP_SEARCH_KEY = 'carnivore.session.sidebar.deepSearch';

export const DRAWER_SEARCH_MODE_KEY = 'carnivore.session.sidebar.searchMode';

/*  hidden  */
export const DRAWER_DEEP_ACTIVE_CLASS = 'drawer-deep-search';

export const QUESTIONS_TAB = 'questions';

export const DRAWER_LEDGER_ID = 'session-sidebar-ledger';

export type NewSessionKind = 'agent' | 'terminal' | 'browser';

export const NEW_SESSION_BROWSER_ENABLED: boolean = true;

export function newSessionKinds(): readonly NewSessionKind[] {
    return NEW_SESSION_BROWSER_ENABLED ? ['agent', 'terminal', 'browser'] : ['agent', 'terminal'];
}

/*  hidden  */
export function applyDrawerTab(tab: string, defs: readonly DynamicTabDef[], doc: Document = document): void {
    let componentBody = false;
    for (const def of defs) {
        if ('component' in def.body) {
            if (def.id === tab) componentBody = true;
            continue;
        }
        for (const id of def.body.containers) {
            const el = doc.getElementById(id);
            if (el) el.hidden = def.id !== tab;
        }
    }
    const body = doc.getElementById(DRAWER_TABBODY_ID);
    if (body) body.hidden = !componentBody;
}
