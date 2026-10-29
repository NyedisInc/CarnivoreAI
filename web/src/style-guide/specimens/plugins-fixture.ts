import { toCplugItem, type CplugRow } from '../../lib/plugins-page/cplugs-adapter';
import type { ManagerAdapter, ManagerItem } from '../../lib/manager-frame/types';
import { t } from '../../lib/i18n/index.svelte';
import { createCatalogPlugins, type CatalogPlugins } from '../../lib/plugins-page/catalog-plugins.svelte';
import type { CatalogHost } from '../../lib/catalog/catalog';
import type { InstallRequest, InstalledItem } from '../../lib/catalog/types';

const row = (id: string, enabled: boolean, asks: string[] = [], extra: Partial<CplugRow> = {}): CplugRow => ({
    ...extra,
    id, name_key: `cplug.${id}.name`, description_key: `cplug.${id}.description`, version: '1.0.0', tier: 'builtin',
    enabled, state: enabled ? 'active' : 'disabled', permissions: { app: asks }, revision: 1, storage_bytes: 0,
});

let rows: CplugRow[] = [
    row('unread', true, [], { icon: 'bell', author: 'Alex (Example-owner)', surfaces: { plugins: ['session-card-action'] } }),
    row('share', false, [], { icon: 'link', author: 'Alex (Example-owner)', surfaces: { plugins: ['session-card-action'] } }),
    row('huddle', false, ['sessions.read', 'notify'], { icon: 'chat', author: 'Joe (ccsliinc)', surfaces: { tabs: ['huddle'], menu_links: ['huddle'], mcp_tools: ['huddle_list'] } }),
    { ...row('flow', true, [], { icon: 'plug', author: 'Joe (ccsliinc)' }), state: 'unavailable', detail: 'start hook failed: OSError', storage_bytes: 48_000 },
    { ...row('mcphealth', true, ['sessions.read', 'sessions.message'], { icon: 'chart', author: 'Joe (ccsliinc)', surfaces: { plugins: ['session-card-action'] } }), state: 'needs_approval', grants: { app: [] }, risks: { 'sessions.read': 'low', 'sessions.message': 'high' } },
];

export const pluginsSpecimenAdapter: ManagerAdapter = {
    list: async () => rows.map((r) => toCplugItem(r, t)),
    setEnabled: async (id: string, enabled: boolean): Promise<ManagerItem> => {
        const plain = id.replace(/^cplug:/, '');
        rows = rows.map((r) => (r.id === plain ? { ...r, enabled, state: enabled ? 'active' : 'disabled' } : r));
        return toCplugItem(rows.find((r) => r.id === plain)!, t);
    },
};

const ledger: InstalledItem[] = [];
const catalogHost = {
    listItems: async () => ({
        items: [
            { id: 'rea/rea', kind: 'plugin', name: 'rea', publisher: 'rea', latest: '6.5.0', card: { title: 'rea', brief: 'an agent plugin that runs the rea mcp server' } },
            { id: 'nyedis/notes-kit', kind: 'plugin', name: 'notes-kit', publisher: 'nyedis', latest: '1.2.0', card: { title: 'notes kit', brief: 'plain skills for keeping project notes' } },
        ],
    }),
    listInstalled: async () => ({ items: ledger }),
    listProjects: async () => [{ name: 'carnivore', path: '/projects/carnivore' }, { name: 'argent', path: '/projects/argent' }],
    currentProjectPath: async () => '/projects/carnivore',
    previewInstall: async (request: InstallRequest) => ({
        digest: 'a'.repeat(64), body_sha: 'b'.repeat(64), plan_token: `plan-${request.item_id}`, files: [{ path: 'SKILL.md' }],
        mcp_servers: request.item_id === 'rea/rea' ? [{ name: 'rea', command: 'npx', args: ['-y', 'rea-agents@6.5.0', 'mcp'], env_keys: ['REA_TOKEN'] }] : [],
    }),
    install: async (request: InstallRequest) => {
        const installed = { install_id: `inst-${ledger.length}`, item_id: request.item_id, scope: request.scope, project_path: request.project_path };
        ledger.push(installed);
        return installed;
    },
    uninstall: async (id: string) => {
        const at = ledger.findIndex((r) => r.install_id === id);
        if (at >= 0) ledger.splice(at, 1);
    },
} as unknown as CatalogHost;

export const pluginsSpecimenCatalog: CatalogPlugins = createCatalogPlugins({ host: catalogHost, t });
