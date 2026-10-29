import type { CatalogHost } from '../catalog/catalog';
import { cardView, type CardView } from '../catalog/card';
import { listedCatalogPlugins, warezOrder } from './plugin-listing';
import { displayKind } from '../catalog/kind-display';
import { refusalCodeOf } from '../catalog/install-actions';
import { quickAdd } from '../catalog/quick-add';
import { consentBlock, needsScriptConsent, scriptFiles } from '../catalog/scripts';
import { mcpServers } from '../catalog/mcp';
import type {
    CatalogItem,
    InstallPreview,
    InstallRequest,
    InstalledItem,
    McpServer,
    SheetOutcome,
} from '../catalog/types';
import type { ManagerItem } from '../manager-frame/types';
import type { ProjectRow, Translate } from '../sessions/types';
import { icons } from '../../opscenter/ui/icons';
import { refusalMessage } from '../../../../client/js/labels/skill.js';

export const CATALOG_ITEM_PREFIX = 'catalog:';

const SHEET_CODES: ReadonlySet<string> = new Set(['consent_required', 'sheet_required', 'name_taken']);

export interface CatalogPluginItem extends ManagerItem {
    readonly kind: 'catalog';
    readonly itemId: string;
    readonly mediaSha: string | null;
    readonly credit: CatalogCredit | null;
}

export interface CatalogCredit {
    readonly sourceUrl: string | null;
    readonly publisher: string | null;
}

function text(value: unknown): string | null {
    return typeof value === 'string' && value.trim() !== '' ? value.trim() : null;
}

function firstWebUrl(candidates: readonly unknown[]): string | null {
    for (const c of candidates) {
        const v = text(c);
        if (v && /^https?:\/\//i.test(v)) return v;
    }
    return null;
}

export type CommandFacts =
    | { readonly kind: 'none' }
    | { readonly kind: 'loading' }
    | { readonly kind: 'failed' }
    | {
          readonly kind: 'ready';
          readonly servers: readonly McpServer[];
          readonly scripts: readonly string[];
      };

export interface PluginAct {
    readonly kind: 'add' | 'update' | 'switch';
    readonly rows: readonly InstalledItem[];
}

export interface CatalogPlugins {
    readonly projects: readonly ProjectRow[];
    readonly projectPath: string | null;
    /* could not be read */
    readonly loadError: string | null;
    load(): Promise<void>;
    pick(path: string | null): Promise<void>;
    items(): CatalogPluginItem[];
    facts(itemId: string): CommandFacts;
    ledger(): readonly InstalledItem[];
    uninstall(installId: string): Promise<unknown>;
    act(itemId: string): PluginAct;
    add(itemId: string, target: 'global' | 'project', projectPath: string | null): Promise<void>;
    update(itemId: string): Promise<void>;
    setEnabled(itemId: string, on: boolean): Promise<CatalogPluginItem>;
}

export interface CatalogPluginsDeps {
    readonly host: CatalogHost;
    readonly t: Translate;
    readonly openSheet?: (
        card: CardView,
        prefill: { scope: 'project'; projectPath: string } | { scope: 'global'; projectPath: null },
    ) => Promise<SheetOutcome | null>;
}

function samePath(a: string | null | undefined, b: string | null | undefined): boolean {
    if (!a || !b) return false;
    return a.replace(/\/+$/, '') === b.replace(/\/+$/, '');
}

function pathOf(project: ProjectRow): string | null {
    return project.path || project.root || null;
}

export function createCatalogPlugins(deps: CatalogPluginsDeps): CatalogPlugins {
    const { host, t } = deps;
    let catalog = $state<CatalogItem[]>([]);
    let installed = $state<InstalledItem[]>([]);
    let projects = $state<ProjectRow[]>([]);
    let projectPath = $state<string | null>(null);
    let loadError = $state<string | null>(null);
    let previews = $state<Record<string, { kind: 'loading' | 'failed' } | { kind: 'ready'; preview: InstallPreview }>>({});
    let seeded = false;
    let generation = 0;

    function projectRow(itemId: string): InstalledItem | undefined {
        return installed.find((r) => r.item_id === itemId && r.scope === 'project' && samePath(r.project_path, projectPath));
    }

    function isCarnivorePlugin(item: CatalogItem): boolean {
        return cardView(item, false).isCplug;
    }

    function isInstalledAnywhere(itemId: string): boolean {
        return installed.some((r) => r.item_id === itemId);
    }

    function listed(): CatalogItem[] {
        return warezOrder(listedCatalogPlugins(catalog, new Set(installed.map((r) => r.item_id as string))));
    }

    function isGlobal(itemId: string): boolean {
        return installed.some((r) => r.item_id === itemId && r.scope === 'global');
    }

    async function readPreview(id: string, path: string, mine: number): Promise<void> {
        let next: (typeof previews)[string];
        try {
            next = { kind: 'ready', preview: await host.previewInstall({ item_id: id, scope: 'project', project_path: path }) };
        } catch {
            next = { kind: 'failed' };
        }
        if (mine === generation) previews = { ...previews, [id]: next };
    }

    async function prefetch(only?: string): Promise<void> {
        const path = projectPath;
        if (!only) {
            ++generation;
            previews = {};
        }
        if (!path) return;
        const mine = generation;
        const todo = listed().filter((item) => item.id && !isCarnivorePlugin(item) && (!only || item.id === only) && !projectRow(item.id) && !isGlobal(item.id));
        previews = { ...previews, ...Object.fromEntries(todo.map((item) => [item.id as string, { kind: 'loading' as const }])) };
        await Promise.all(todo.map((item) => readPreview(item.id as string, path, mine)));
    }

    async function reloadInstalled(): Promise<void> {
        installed = (await host.listInstalled()).items ?? [];
    }

    function actOf(item: CatalogItem): PluginAct {
        const rows = installed.filter((r) => r.item_id === item.id);
        return { kind: rows.length === 0 ? 'add' : rows.some((r) => r.update_available === true) ? 'update' : 'switch', rows };
    }

    function toItem(item: CatalogItem): CatalogPluginItem {
        const card = cardView(item, false);
        const id = item.id as string;
        const glob = isGlobal(id);
        const fm = (item.fm ?? {}) as Record<string, unknown>;
        const author = text(fm.author);
        return {
            id: `${CATALOG_ITEM_PREFIX}${id}`,
            kind: 'catalog',
            itemId: id,
            mediaSha: card.mediaSha,
            name: card.headline ?? id,
            brief: card.brief,
            meta: card.version,
            icon: card.icon && card.icon in icons ? card.icon : 'plug',
            tags: glob ? [t('plugins.page.catalog.global')] : [],
            byline: author ? t('plugins.page.byline', { name: author }) : card.publisher ? t('plugins.page.byline', { name: card.publisher }) : null,
            credit: author ? { sourceUrl: firstWebUrl([fm.homepage, fm.repository, fm.author_url]), publisher: card.publisher } : null,
            enabled: glob || actOf(item).kind !== 'switch' ? null : isCarnivorePlugin(item) ? false : projectPath ? projectRow(id) !== undefined : false,
        };
    }

    async function viaSheet(item: CatalogItem): Promise<CatalogPluginItem> {
        const global = isCarnivorePlugin(item);
        if (!deps.openSheet || (!global && !projectPath)) throw new Error(t('plugins.page.catalog.sheet_unavailable'));
        await deps.openSheet(cardView(item, false), global ? { scope: 'global', projectPath: null } : { scope: 'project', projectPath: projectPath as string });
        await reloadInstalled();
        return toItem(item);
    }

    return {
        get projects() {
            return projects;
        },
        get projectPath() {
            return projectPath;
        },
        get loadError() {
            return loadError;
        },
        async load() {
            try {
                const [list, ledger, rows] = await Promise.all([host.listItems(), host.listInstalled(), host.listProjects()]);
                catalog = (list.items ?? []).filter((item) => displayKind(item.kind) === 'plugin' && typeof item.id === 'string' && item.id !== '');
                installed = ledger.items ?? [];
                projects = rows;
                loadError = null;
            } catch {
                catalog = [];
                loadError = t('plugins.page.catalog.load_failed');
                return;
            }
            if (!seeded) {
                seeded = true;
                const current = await host.currentProjectPath().catch(() => null);
                const known = projects.map(pathOf).find((p) => samePath(p, current));
                if (known) projectPath = known;
            }
            void prefetch();
        },
        async pick(path) {
            projectPath = path && projects.some((p) => samePath(pathOf(p), path)) ? path : null;
            await prefetch();
        },
        items: () => listed().map(toItem),
        ledger: () => installed,
        uninstall: (installId) => host.uninstall(installId),
        facts(itemId) {
            if (projectRow(itemId) || isGlobal(itemId)) return { kind: 'none' };
            const state = previews[itemId];
            if (!state) return { kind: 'none' };
            if (state.kind !== 'ready') return state;
            return {
                kind: 'ready',
                servers: mcpServers(state.preview),
                scripts: scriptFiles(state.preview).map((f) => String(f.path ?? '')),
            };
        },
        act(itemId) {
            const item = catalog.find((c) => c.id === itemId);
            return item ? actOf(item) : { kind: 'switch', rows: [] };
        },
        async add(itemId, target, path) {
            const item = catalog.find((c) => c.id === itemId);
            if (!item) throw new Error(t('plugins.page.catalog.gone'));
            const answer = await quickAdd(host, itemId, target, path);
            if (answer.outcome === 'refused') throw new Error(answer.code ? refusalMessage(answer.code, t) : t('plugins.page.catalog.failed'));
            if (answer.outcome === 'sheet') {
                if (!deps.openSheet) throw new Error(t('plugins.page.catalog.sheet_unavailable'));
                await deps.openSheet(cardView(item, false), answer.prefill as never);
            }
            await reloadInstalled();
        },
        async update(itemId) {
            const item = catalog.find((c) => c.id === itemId);
            if (!item) throw new Error(t('plugins.page.catalog.gone'));
            if (!deps.openSheet) throw new Error(t('plugins.page.catalog.sheet_unavailable'));
            await deps.openSheet(cardView(item, false), null as never);
            await reloadInstalled();
        },
        async setEnabled(itemId, on) {
            const item = catalog.find((c) => c.id === itemId);
            if (!item) throw new Error(t('plugins.page.catalog.gone'));
            if (isCarnivorePlugin(item)) return on ? viaSheet(item) : toItem(item);
            if (!projectPath) throw new Error(t('plugins.page.catalog.need_project'));
            if (!on) {
                const row = projectRow(itemId);
                if (row?.install_id) await host.uninstall(row.install_id);
                await reloadInstalled();
                await prefetch(itemId);
                return toItem(item);
            }
            const shown = previews[itemId];
            if (!shown || shown.kind !== 'ready') return viaSheet(item);
            const owed = needsScriptConsent(shown.preview);
            const block = owed ? consentBlock(shown.preview) : null;
            if (owed && !block) return viaSheet(item);
            const body: InstallRequest = {
                item_id: itemId,
                scope: 'project',
                project_path: projectPath,
                ...(shown.preview.plan_token ? { plan_token: shown.preview.plan_token } : {}),
                ...(block ? { consent: block } : {}),
            };
            try {
                await host.install(body);
            } catch (error) {
                const code = refusalCodeOf(error);
                if (code && SHEET_CODES.has(code)) return viaSheet(item);
                throw new Error(code ? refusalMessage(code, t) : error instanceof Error && error.message ? error.message : t('plugins.page.catalog.failed'));
            }
            await reloadInstalled();
            return toItem(item);
        },
    };
}
