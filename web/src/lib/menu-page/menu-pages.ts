/* the page frame */

import type { PageFrame } from '../../opscenter/ui/page-frame';

export interface MenuPage {
    readonly id: string;
    readonly containerId: string;
    readonly closer: string;
    readonly railItem: string | null;
    readonly hashes: readonly string[];
    /* the Task Manager */
    readonly keepDrawerTab?: boolean;
    readonly frame: PageFrame;
}

export const MENU_PAGES: readonly MenuPage[] = [
    { id: 'dashboards', containerId: 'dashboards-screen', closer: 'closeDashboardsScreen', railItem: 'dashboards', hashes: ['#dashboards'], frame: 'column' },
    { id: 'hosts', containerId: 'hosts-screen', closer: 'closeHostsScreen', railItem: 'hosts', hashes: ['#pack', '#hosts'], frame: 'column' },
    { id: 'sessions', containerId: 'sessions-screen', closer: 'closeSessionsScreen', railItem: 'sessions', hashes: ['#sessions', '#projects'], frame: 'nav' },
    { id: 'plugins', containerId: 'plugins-screen', closer: 'closePluginsScreen', railItem: 'plugins', hashes: ['#plugins', '#swarm-settings', '#interactive-todo'], frame: 'column' },
    { id: 'themes', containerId: 'themes-screen', closer: 'closeThemesScreen', railItem: 'themes', hashes: ['#themes'], frame: 'column' },
    { id: 'warez', containerId: 'warez-screen', closer: 'closeWarezScreen', railItem: 'warez', hashes: ['#warez', '#catalog', '#skills', '#skills-manager'], frame: 'nav' },
    { id: 'elite', containerId: 'elite-screen', closer: 'closeEliteScreen', railItem: 'warez', hashes: ['#elite'], frame: 'column' },
    { id: 'settings', containerId: 'settings-screen', closer: 'closeSettingsScreen', railItem: 'settings', hashes: ['#settings', '#wrappers', '#launch-profiles', '#shortcuts'], frame: 'nav' },
    { id: 'account', containerId: 'account-screen', closer: 'closeAccountScreen', railItem: null, hashes: ['#account'], frame: 'column' },
    { id: 'widgets', containerId: 'widgets-screen', closer: 'closeWidgetsScreen', railItem: 'widgets', hashes: ['#widgets'], frame: 'nav' },
    { id: 'ledger', containerId: 'ledger-screen', closer: 'closeLedgerScreen', railItem: 'providers', hashes: ['#ledger'], frame: 'column' },
    { id: 'blueprints', containerId: 'blueprints-screen', closer: 'closeBlueprintsScreen', railItem: 'blueprints', hashes: ['#blueprints'], frame: 'column' },
    { id: 'docs', containerId: 'docs-screen', closer: 'closeDocsScreen', railItem: 'docs', hashes: ['#docs'], frame: 'column' },
    { id: 'huddle-agent', containerId: 'huddle-agent-screen', closer: 'closeHuddleAgentScreen', railItem: null, hashes: ['#agent'], keepDrawerTab: true, frame: 'column' },
    { id: 'huddle-swarm', containerId: 'huddle-swarm-screen', closer: 'closeHuddleSwarmScreen', railItem: null, hashes: ['#swarm'], keepDrawerTab: true, frame: 'column' },
    { id: 'mods', containerId: 'mods-screen', closer: 'closeModsScreen', railItem: 'mods', hashes: ['#mods'], frame: 'column' },
    { id: 'automations', containerId: 'automations-screen', closer: 'closeAutomationsScreen', railItem: 'automations', hashes: ['#automations'], frame: 'column' },
    { id: 'changelog', containerId: 'changelog-screen', closer: 'closeChangelogScreen', railItem: 'changelog', hashes: ['#changelog'], frame: 'column' },
    { id: 'logs', containerId: 'logs-screen', closer: 'closeLogsScreen', railItem: null, hashes: ['#logs'], frame: 'column' },
    { id: 'warroom', containerId: 'warroom-screen', closer: 'closeWarroomScreen', railItem: 'warroom', hashes: ['#warroom'], frame: 'canvas' },
];

export function menuPage(id: string): MenuPage | null {
    return MENU_PAGES.find((p) => p.id === id) ?? null;
}

export const MENU_PAGE_OPEN_CLASS = 'menu-page-open';
