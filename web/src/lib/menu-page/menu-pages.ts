
export interface MenuPage {
    readonly id: string;
    readonly containerId: string;
    readonly closer: string;
    readonly railItem: string | null;
    readonly hashes: readonly string[];
    readonly keepDrawerTab?: boolean;
}

export const MENU_PAGES: readonly MenuPage[] = [
    { id: 'dashboards', containerId: 'dashboards-screen', closer: 'closeDashboardsScreen', railItem: 'dashboards', hashes: ['#dashboards'] },
    { id: 'hosts', containerId: 'hosts-screen', closer: 'closeHostsScreen', railItem: 'hosts', hashes: ['#pack', '#hosts'] },
    { id: 'sessions', containerId: 'sessions-screen', closer: 'closeSessionsScreen', railItem: 'sessions', hashes: ['#sessions', '#projects'] },
    { id: 'plugins', containerId: 'plugins-screen', closer: 'closePluginsScreen', railItem: 'plugins', hashes: ['#plugins', '#swarm-settings', '#interactive-todo'] },
    { id: 'themes', containerId: 'themes-screen', closer: 'closeThemesScreen', railItem: 'themes', hashes: ['#themes'] },
    { id: 'warez', containerId: 'warez-screen', closer: 'closeWarezScreen', railItem: 'warez', hashes: ['#warez', '#catalog', '#skills', '#skills-manager'] },
    { id: 'elite', containerId: 'elite-screen', closer: 'closeEliteScreen', railItem: 'warez', hashes: ['#elite'] },
    { id: 'settings', containerId: 'settings-screen', closer: 'closeSettingsScreen', railItem: 'settings', hashes: ['#settings', '#wrappers', '#launch-profiles', '#shortcuts'] },
    { id: 'account', containerId: 'account-screen', closer: 'closeAccountScreen', railItem: null, hashes: ['#account'] },
    { id: 'widgets', containerId: 'widgets-screen', closer: 'closeWidgetsScreen', railItem: null, hashes: ['#widgets'] },
    { id: 'ledger', containerId: 'ledger-screen', closer: 'closeLedgerScreen', railItem: 'providers', hashes: ['#ledger'] },
    { id: 'blueprints', containerId: 'blueprints-screen', closer: 'closeBlueprintsScreen', railItem: 'blueprints', hashes: ['#blueprints'] },
    { id: 'docs', containerId: 'docs-screen', closer: 'closeDocsScreen', railItem: 'docs', hashes: ['#docs'] },
    { id: 'huddle-agent', containerId: 'huddle-agent-screen', closer: 'closeHuddleAgentScreen', railItem: null, hashes: ['#agent'], keepDrawerTab: true },
    { id: 'huddle-swarm', containerId: 'huddle-swarm-screen', closer: 'closeHuddleSwarmScreen', railItem: null, hashes: ['#swarm'], keepDrawerTab: true },
    { id: 'mods', containerId: 'mods-screen', closer: 'closeModsScreen', railItem: 'mods', hashes: ['#mods'] },
    { id: 'automations', containerId: 'automations-screen', closer: 'closeAutomationsScreen', railItem: 'automations', hashes: ['#automations'] },
    { id: 'changelog', containerId: 'changelog-screen', closer: 'closeChangelogScreen', railItem: 'changelog', hashes: ['#changelog'] },
    { id: 'logs', containerId: 'logs-screen', closer: 'closeLogsScreen', railItem: null, hashes: ['#logs'] },
    { id: 'warroom', containerId: 'warroom-screen', closer: 'closeWarroomScreen', railItem: 'warroom', hashes: ['#warroom'] },
];

export function menuPage(id: string): MenuPage | null {
    return MENU_PAGES.find((p) => p.id === id) ?? null;
}

export const MENU_PAGE_OPEN_CLASS = 'menu-page-open';
