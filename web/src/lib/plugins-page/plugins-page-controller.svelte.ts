import { isCplugIndexKind } from '../catalog/kind-display';
import { disableAndUninstallPlugin } from '../catalog/revocation';
import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
import { latestOnly } from '../resource-push/latest-only';
import { openModalCount } from '../modal';
import type { ManagerToggleState } from '../manager-frame/types';
import type { Translate } from '../sessions/types';
import type { CatalogPluginItem, CatalogPlugins } from './catalog-plugins.svelte';
import { setCplugEnabled, type CplugItem, type CplugSheet } from './cplugs-adapter';
import { uninstallPlugin, uninstallableRow } from './plugin-uninstall';

export interface PluginsPageDeps {
    catalog: CatalogPlugins | null;
    catalogItems: () => CatalogPluginItem[];
    reloadBuiltins: () => Promise<void>;
    loadSheet: (cplugId: string) => Promise<CplugSheet>;
    t: Translate;
}

export interface PluginsPageController {
    readonly toggles: Record<string, ManagerToggleState>;
    readonly uninstallingId: string | null;
    readonly uninstallErrors: Record<string, string | null>;
    readonly seenSheets: Record<string, CplugSheet>;
    toggleCatalog(id: string, next: boolean): Promise<void>;
    runAct(id: string, run: () => Promise<void>): Promise<void>;
    ledgerRowOf(plugin: CplugItem): ReturnType<typeof uninstallableRow>;
    uninstallFromPane(plugin: CplugItem): Promise<void>;
    disableAndUninstallRevoked(plugin: CplugItem): Promise<void>;
    readSheetFor(cplugId: string): void;
}

export function createPluginsPageController(deps: PluginsPageDeps): PluginsPageController {
    const { catalog, t } = deps;
    let toggles = $state<Record<string, ManagerToggleState>>({});
    let uninstallingId = $state<string | null>(null);
    let uninstallErrors = $state<Record<string, string | null>>({});
    let seenSheets = $state<Record<string, CplugSheet>>({});
    const sheetGate = latestOnly();

    async function runBusy(id: string, work: () => Promise<void>): Promise<void> {
        if (toggles[id]?.busy) return;
        toggles = { ...toggles, [id]: { busy: true, error: null } };
        try {
            await work();
            toggles = { ...toggles, [id]: { busy: false, error: null } };
        } catch (error) {
            toggles = { ...toggles, [id]: { busy: false, error: nonEmptyErrorMessageOr(error, t('plugins.page.catalog.failed')) } };
        }
    }

    function ledgerRowOf(plugin: CplugItem): ReturnType<typeof uninstallableRow> {
        if (!catalog) return undefined;
        if (plugin.installId) {
            const byInstallId = catalog.ledger().find(
                (row) => row.install_id === plugin.installId && (isCplugIndexKind(row.kind) || row.kind === 'plugin') && row.source_index_url !== 'builtin',
            );
            if (byInstallId) return byInstallId;
        }
        if (!plugin.thirdParty && plugin.pluginKind !== 'agent-plugin') return undefined;
        const lookupId = plugin.itemId || (plugin.publisher ? `${plugin.publisher}/${plugin.cplugId}` : '');
        return lookupId ? uninstallableRow(catalog.ledger(), lookupId) : undefined;
    }

    return {
        get toggles() { return toggles; },
        get uninstallingId() { return uninstallingId; },
        get uninstallErrors() { return uninstallErrors; },
        get seenSheets() { return seenSheets; },

        async toggleCatalog(id, next) {
            const item = deps.catalogItems().find((row) => row.id === id);
            if (!catalog || !item) return;
            await runBusy(id, async () => {
                await catalog.setEnabled(item.itemId, next);
                if (next && !catalog.items().some((row) => row.id === id)) void deps.reloadBuiltins();
            });
        },

        runAct: runBusy,

        ledgerRowOf,

        async uninstallFromPane(plugin) {
            const row = ledgerRowOf(plugin);
            if (!row || !catalog || uninstallingId !== null || openModalCount() > 0) return;
            uninstallingId = plugin.id;
            uninstallErrors = { ...uninstallErrors, [plugin.id]: null };
            try {
                const result = await uninstallPlugin(row, plugin.name, catalog, t);
                uninstallErrors = { ...uninstallErrors, [plugin.id]: result.error };
                if (result.done) await Promise.all([catalog.load(), deps.reloadBuiltins()]);
            } finally {
                uninstallingId = null;
            }
        },

        async disableAndUninstallRevoked(plugin) {
            if (!catalog || uninstallingId !== null) return;
            const row = ledgerRowOf(plugin);
            if (!row?.install_id) return;
            uninstallingId = plugin.id;
            uninstallErrors = { ...uninstallErrors, [plugin.id]: null };
            try {
                const result = await disableAndUninstallPlugin({
                    enabled: plugin.enabled ?? null,
                    disable: () => setCplugEnabled(plugin.id, false, t, undefined, async () => {}, true),
                    installId: row.install_id,
                    uninstall: (installId) => catalog.uninstall(installId),
                    row,
                    t,
                });
                uninstallErrors = { ...uninstallErrors, [plugin.id]: result.error };
                if (result.done) await Promise.all([catalog.load(), deps.reloadBuiltins()]);
            } finally {
                uninstallingId = null;
            }
        },

        readSheetFor(cplugId) {
            const current = sheetGate.begin();
            deps.loadSheet(cplugId).then(
                (sheet) => { if (current()) seenSheets = { ...seenSheets, [cplugId]: sheet }; },
                () => { if (current()) { const { [cplugId]: _gone, ...rest } = seenSheets; seenSheets = rest; } },
            );
        },
    };
}
