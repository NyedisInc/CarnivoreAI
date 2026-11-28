
<script lang="ts">
    import { mountInto } from '../mount';
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import StatusChip from '../cplug-ui/StatusChip.svelte';
    import { canDrawGlance } from '../cplug-ui/glance';
    import { createManagerController } from '../manager-frame/manager-controller.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { ManagerAdapter, ManagerFilter, ManagerItem, ManagerToggleState } from '../manager-frame/types';
    import { t as appT } from '../i18n/index.svelte';
    import { openPluginStudio } from '../plugin-studio/screen-host';
    import type { Translate } from '../sessions/types';
    import PluginPane from './PluginPane.svelte';
    import PluginPaneStrip from './PluginPaneStrip.svelte';
    import PluginHealthPill from './PluginHealthPill.svelte';
    import PluginInstallSheet from './PluginInstallSheet.svelte';
    import DevInspectorDrawer from './DevInspectorDrawer.svelte';
    import { isRuntimeDisabledDetail } from './install-sheet-model';
    import { createPluginActions } from './plugin-actions.svelte';
    import { openModal, openModalCount } from '../modal';
    import InstallSheet from '../catalog/InstallSheet.svelte';
    import { browserCatalogHost } from '../catalog/catalog';
    import type { CardView } from '../catalog/card';
    import type { InstallScope, InstalledItem, SheetOutcome } from '../catalog/types';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import SideloadLoadForm from './SideloadLoadForm.svelte';
    import SideloadRowActions from './SideloadRowActions.svelte';
    import { createSideloadStore } from './sideload-store.svelte';
    import CardMediaImg from '../catalog/CardMediaImg.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import IconButton from '../base/IconButton.svelte';
    import Button from '../base/Button.svelte';
    import Tag from '../base/Tag.svelte';
    import RevokedBanner from '../catalog/RevokedBanner.svelte';
    import AddSplit from '../catalog/AddSplit.svelte';
    import { addProjectsOf } from '../catalog/add-projects';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import CatalogPluginFacts from './CatalogPluginFacts.svelte';
    import CatalogPluginCredit from './CatalogPluginCredit.svelte';
    import { CATALOG_ITEM_PREFIX, createCatalogPlugins, type CatalogPluginItem, type CatalogPlugins } from './catalog-plugins.svelte';
    import { readTab, writeTab } from '../../opscenter/ui/tab-memory';
    import { grantCplug, readSheet, sheetStamp, type GrantOptions } from './cplug-grant';
    import { CPLUG_ITEM_PREFIX, createCplugsAdapter, isCplugRow, listActivity, listCplugItems, toCplugItem, type ActivityRow, type CplugItem, type CplugSheet, type CplugUiSlotRow, type CplugsAdapter } from './cplugs-adapter';
    import { PANE_TAB_MEMORY, PANE_TABS, isPaneTab, type PaneTab, type PurgePrice } from './plugin-pane';
    import { hasPluginSettings, pluginLinkOf, type PluginLink } from './plugin-settings-link';
    import ClaudeCodeHealth from './ClaudeCodeHealth.svelte';
    import { createPluginHealth } from './plugin-health.svelte';
    import { canRun, runHealthButton, type HealthDoors, type HealthSubject } from './plugin-health-actions';
    import type { HealthRow } from './plugin-health';
    import { pluginsStore, type StoreCplugRow } from '../plugins/store.svelte';

    import { isFeatureTier } from '../catalog/app-own';
    import { featureWords } from './feature-words';
    import type { PluginsScreenProps } from './plugins-screen-props';
    import { createPluginsPageController } from './plugins-page-controller.svelte';
    import { replaceHashWith, rowsInScope } from './plugin-scope';
    import { SWARM_ITEM_ID, resolveSwarmSelectionTarget, swarmFeatureItem } from './swarm-feature';
    import { startSwarmSwitch, swarmSwitch, toggleSwarm } from '../swarm-switch/control.svelte';

    const { adapter, t: tProp = appT, embedded = false, focusId = null, focusTab = null, onSelect: onPick, onChanged, storeOnly = false, scope, developerMode = false, grant = (id, ticks, options) => grantCplug(id, ticks, t, undefined, undefined, options), loadSheet = readSheet, loadActivity = listActivity, purge, catalog: catalogProp, onInspectLogs }: PluginsScreenProps = $props();

    // svelte-ignore state_referenced_locally
    const t: Translate = scope === 'features' ? featureWords(tProp) : tProp;

    if (scope === 'features') startSwarmSwitch();

    // svelte-ignore state_referenced_locally
    const baseAdapter: ManagerAdapter & Partial<CplugsAdapter> = adapter ?? createCplugsAdapter(t);
    // svelte-ignore state_referenced_locally
    const pageAdapter: ManagerAdapter & Partial<CplugsAdapter> =
        !adapter && scope === 'features' ? { ...baseAdapter, list: () => listCplugItems(t, undefined, false) } : baseAdapter;
    // svelte-ignore state_referenced_locally
    const ctl = createManagerController(pageAdapter, t(MANAGER_KEYS.errorTitle));
    // svelte-ignore state_referenced_locally
    const actions = createPluginActions({ ctl, adapter: pageAdapter, grant, seenSheet: (id) => page.seenSheets[id], onAsk: (id) => (selectedId = id) });
    // svelte-ignore state_referenced_locally
    const sideloads = adapter ? null : createSideloadStore(undefined, () => void ctl.load());

    // svelte-ignore state_referenced_locally
    const health = adapter || scope === 'features' ? null : createPluginHealth();

    let seenSig: string | null = null;
    $effect(() => {
        const sig = ctl.items.map((row) => `${row.id}:${row.enabled ?? ''}`).join('|');
        const before = seenSig;
        seenSig = sig;
        if (before !== null && before !== sig) {
            onChanged?.();
            void health?.load();
        }
    });

    interface InstallSheetModalState {
        readonly mode: 'github' | 'catalog' | 'enable';
        readonly card?: CardView | null;
        readonly item?: CplugItem | null;
        readonly initialScope?: InstallScope | null;
        readonly initialProject?: string | null;
        readonly resolve?: (outcome: SheetOutcome | null) => void;
    }

    let installSheet = $state<InstallSheetModalState | null>(null);
    let folderOpen = $state(false);
    let folderButton = $state<HTMLElement | null>(null);

    function rowIndicatesInactiveRuntime(row: StoreCplugRow): boolean {
        return (row as { readonly runtime_active?: boolean }).runtime_active === false || isRuntimeDisabledDetail(row.detail);
    }

    function itemIndicatesInactiveRuntime(plugin: CplugItem): boolean {
        const extra = plugin as CplugItem & { readonly runtimeActive?: boolean; readonly detail?: string | null };
        return (
            extra.runtimeActive === false ||
            isRuntimeDisabledDetail(plugin.heldReason) ||
            isRuntimeDisabledDetail(extra.detail)
        );
    }

    async function openCatalogSheet(card: CardView, prefill: { scope: 'project'; projectPath: string } | { scope: 'global'; projectPath: null }): Promise<SheetOutcome | null> {
        if (openModalCount() > 0 || installSheet !== null) return null;
        if (card.isCplug || card.isPlugin) {
            return new Promise<SheetOutcome | null>((resolve) => {
                installSheet = {
                    mode: 'catalog',
                    card,
                    initialScope: prefill.scope,
                    initialProject: prefill.projectPath ?? null,
                    resolve,
                };
            });
        }
        return (await openModal(InstallSheet as never, { card, host: browserCatalogHost(), t, prefill } as never)) as SheetOutcome | null;
    }

    function openGithubSheet(): void {
        if (openModalCount() > 0 || installSheet !== null) return;
        installSheet = { mode: 'github' };
    }

    function needsEnableSheet(plugin: CplugItem | undefined): boolean {
        if (!plugin || !plugin.thirdParty || plugin.pluginKind === 'agent-plugin') return false;
        const extra = plugin as CplugItem & { readonly needsSecret?: boolean };
        const hasSecrets = Boolean(extra.needsSecret || (plugin.secretsStatus && Object.keys(plugin.secretsStatus).length > 0));
        return Boolean(plugin.consentRequired || hasSecrets || itemIndicatesInactiveRuntime(plugin));
    }

    function closeInstallSheet(): void {
        const pending = installSheet;
        installSheet = null;
        pending?.resolve?.(null);
    }

    function finishInstallSheet(result: { id?: string; enabled: boolean; scope?: InstallScope; projectPath?: string | null }): void {
        const pending = installSheet;
        installSheet = null;
        if (pending?.mode === 'catalog' && pending.card) {
            const resolvedScope = result.scope ?? pending.initialScope ?? 'global';
            const resolvedProject = resolvedScope === 'project' ? (result.projectPath ?? pending.initialProject ?? null) : null;
            const row = {
                install_id: result.id ?? '',
                item_id: pending.card.id ?? '',
                name: pending.card.name ?? result.id ?? '',
                scope: resolvedScope,
                ...(resolvedProject ? { project_path: resolvedProject } : {}),
            } as InstalledItem;
            pending.resolve?.({ outcome: 'installed', row });
        }
        void loadAll();
    }

    function inspectLogs(cplugId: string): void {
        if (onInspectLogs) {
            onInspectLogs(cplugId);
            return;
        }
        inspectedPluginId = cplugId;
    }

    // svelte-ignore state_referenced_locally
    const catalog: CatalogPlugins | null =
        catalogProp !== undefined ? catalogProp : adapter || scope === 'features' ? null : createCatalogPlugins({ host: browserCatalogHost(), t, openSheet: openCatalogSheet });
    const catalogItems = $derived<CatalogPluginItem[]>(catalog ? catalog.items() : []);
    // svelte-ignore state_referenced_locally
    const page = createPluginsPageController({ catalog, catalogItems: () => catalogItems, reloadBuiltins: () => ctl.load(), loadSheet, t });

    const agentPluginIds = $derived(
        new Set(
            (ctl.items as CplugItem[])
                .filter((item) => isCplugRow(item) && item.pluginKind === 'agent-plugin')
                .flatMap((item) => [item.cplugId, item.itemId ?? ''].filter(Boolean)),
        ),
    );

    const claudeRows = $derived<HealthRow[]>(
        scope === 'features' ? [] : (health?.claudeCode ?? []).filter((row) => !agentPluginIds.has(row.id)),
    );

    const sheetRuntimeActive = $derived.by((): boolean | undefined => {
        if (installSheet?.mode === 'enable' && installSheet.item) {
            const target = installSheet.item;
            const itemRuntime = (target as CplugItem & { readonly runtimeActive?: boolean }).runtimeActive;
            if (itemRuntime !== undefined) return itemRuntime;
            const storeRow = pluginsStore.rowOf(target.cplugId);
            const storeRuntime = (storeRow as (StoreCplugRow & { readonly runtime_active?: boolean }) | undefined)?.runtime_active;
            if (storeRuntime !== undefined) return storeRuntime;
            if (itemIndicatesInactiveRuntime(target)) return false;
            const healthRow = health?.rowOf(target);
            if (healthRow?.reason === 'third_party_off' || healthRow?.button === 'turn_on_third_party') return false;
            return undefined;
        }
        if (installSheet?.mode === 'catalog') {
            if (pluginsStore.rows.some((row) => row.runtime === 'sidecar' && rowIndicatesInactiveRuntime(row))) return false;
            if ((ctl.items as CplugItem[]).some((row) => isCplugRow(row) && row.thirdParty && row.pluginKind !== 'agent-plugin' && itemIndicatesInactiveRuntime(row))) {
                return false;
            }
            if (health?.report?.rows.some((row) => row.reason === 'third_party_off' || row.button === 'turn_on_third_party')) {
                return false;
            }
        }
        return undefined;
    });

    const healthDoors: HealthDoors = {
        toggle: (itemId, next) => requestToggle(itemId, next),
        openPane: (itemId, tab) => { selectedId = itemId; paneTab = tab; tellHost(); },
        select: (itemId) => { selectedId = itemId; tellHost(); },
        openDeveloperZone: () => {
            const candidate =
                (ctl.items as CplugItem[]).find(
                    (row) => row.id === selectedId && isCplugRow(row) && row.thirdParty && row.pluginKind !== 'agent-plugin',
                ) ??
                (ctl.items as CplugItem[]).find(
                    (row) =>
                        isCplugRow(row) &&
                        row.thirdParty &&
                        row.pluginKind !== 'agent-plugin' &&
                        (itemIndicatesInactiveRuntime(row) || row.state === 'unavailable' || row.state === 'disabled'),
                );
            if (candidate) {
                installSheet = { mode: 'enable', item: candidate };
                return;
            }
            if (sideloads) {
                void sideloads.setSwitch(true).then(() => loadAll()).catch(() => {});
                return;
            }
            openGithubSheet();
        },
        openCatalog: () => replaceHashWith('#warez'),
        leaveSafeMode: async () => { await health?.leaveSafeMode(); },
    };

    function subjectOf(plugin: CplugItem): HealthSubject {
        return { itemId: plugin.id, blockedBy: plugin.blockedBy };
    }

    const addProjects = $derived(addProjectsOf(catalog?.projects ?? [], null));
    const sheetProjects = $derived(
        (catalog?.projects ?? []).flatMap((project) => {
            const path = project.path || project.root;
            return path ? [{ path, name: project.name || path }] : [];
        }),
    );

    async function loadAll(): Promise<void> {
        void catalog?.load();
        void health?.load();
        void sideloads?.refresh();
        await ctl.load();
    }

    function requestToggle(id: string, next: boolean): void {
        if (id === SWARM_ITEM_ID) {
            void toggleSwarm(next);
            return;
        }
        if (id.startsWith(CATALOG_ITEM_PREFIX)) {
            void page.toggleCatalog(id, next);
            return;
        }
        if (next && id.startsWith(CPLUG_ITEM_PREFIX)) {
            const plugin = (ctl.items as CplugItem[]).find((row) => row.id === id);
            if (needsEnableSheet(plugin)) {
                installSheet = { mode: 'enable', item: plugin };
                return;
            }
        }
        actions.request(id, next);
    }

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');
    let featureChip = $state<'on' | 'off' | null>(null);
    let pluginFilter = $state<'enabled' | 'builtin' | 'app' | 'agent' | 'local_dev' | null>(null);
    let selectedId = $state<string | null>(null);
    let inspectedPluginId = $state<string | null>(null);
    let actionsEl = $state<HTMLElement | null>(null);
    let sortKey = $state<'featured' | 'name' | 'state'>('featured');

    const inspectedPlugin = $derived.by((): CplugItem | null => {
        if (!inspectedPluginId) return null;
        const fromCtl = (ctl.items as CplugItem[]).find(
            (item) => isCplugRow(item) && item.cplugId === inspectedPluginId,
        );
        if (fromCtl) return fromCtl;
        const storeRow = pluginsStore.rowOf(inspectedPluginId);
        return storeRow ? toCplugItem(storeRow, t) : null;
    });

    // svelte-ignore state_referenced_locally
    const inspectorProps = $state({
        open: true,
        cplugId: null as string | null,
        plugin: null as CplugItem | null,
        useStore: !adapter,
        busy: false,
        onClose: () => {
            inspectedPluginId = null;
        },
        onRestart: (id: string) => pluginsStore.restartPlugin(id),
        onPauseToggle: (id: string, paused: boolean) =>
            paused ? pluginsStore.pausePlugin(id) : pluginsStore.resumePlugin(id),
        t,
    });

    $effect(() => {
        inspectorProps.cplugId = inspectedPluginId;
        inspectorProps.plugin = inspectedPlugin;
        inspectorProps.busy = inspectedPlugin ? ctl.toggles[inspectedPlugin.id]?.busy === true : false;
    });

    $effect(() => {
        if (!open || inspectedPluginId === null || typeof document === 'undefined') return;
        const host = actionsEl?.closest('.oc-page')?.parentElement ?? document.body;
        return mountInto(host, DevInspectorDrawer, inspectorProps);
    });

    $effect(() => {
        if (adapter || !open) return;
        const stopStore = pluginsStore.acquire({ includeAgentPlugins: scope !== 'features' });
        const stopRows = pluginsStore.onRows(() => {
            void ctl.load();
        });
        return () => {
            stopRows();
            stopStore();
        };
    });

    $effect(() => {
        if (adapter || !open || scope === 'features') return;
        const sidecars = (ctl.items as CplugItem[]).filter(
            (item) =>
                isCplugRow(item) &&
                item.thirdParty &&
                item.pluginKind !== 'agent-plugin' &&
                item.state !== 'removed' &&
                (item.id === selectedId || item.enabled === true),
        );
        const stops = sidecars.map((item) => pluginsStore.acquireInspector(item.cplugId, item.installKey));
        return () => {
            for (const stop of stops) stop();
        };
    });
    const sorted = $derived.by(() => {
        const swarmRow = scope === 'features' ? swarmFeatureItem(swarmSwitch.data, t) : null;
        const builtins: ManagerItem[] = [...rowsInScope(ctl.items as CplugItem[], { scope, developerMode, storeOnly }), ...(swarmRow ? [swarmRow] : [])];
        if (sortKey === 'featured') return [...builtins.sort((a, b) => a.name.localeCompare(b.name)), ...catalogItems];
        return [...builtins, ...catalogItems].sort(
            (a, b) => (sortKey === 'state' ? Number(b.enabled === true) - Number(a.enabled === true) : 0) || a.name.localeCompare(b.name),
        );
    });

    const remembered = readTab(PANE_TAB_MEMORY, PANE_TABS, 'overview');
    let paneTab = $state<PaneTab>(isPaneTab(remembered) ? remembered : 'overview');

    function pickTab(id: PaneTab): void {
        paneTab = id;
        writeTab(PANE_TAB_MEMORY, id);
        tellHost();
    }

    $effect(() => {
        const item = ctl.items.find((row) => row.id === selectedId) as CplugItem | undefined;
        if (paneTab !== 'permissions' || !item?.consentRequired || (item.state !== 'disabled' && item.state !== 'needs_approval')) return;
        page.readSheetFor(item.cplugId);
    });

    function tellHost(): void {
        if (selectedId?.startsWith(CPLUG_ITEM_PREFIX)) onPick?.(selectedId.slice(CPLUG_ITEM_PREFIX.length), paneTab);
    }

    function openSheet(itemId: string): void {
        selectedId = itemId;
        paneTab = 'permissions';
        tellHost();
    }

    function applyLink(link: PluginLink | null, report = true): void {
        if (!link) return;
        selectedId = `${CPLUG_ITEM_PREFIX}${link.cplugId}`;
        if (link.settings) paneTab = 'settings';
        if (report) tellHost();
    }

    // svelte-ignore state_referenced_locally
    if (embedded) {
        void loadAll();
        applyLink(pluginLinkOf(typeof window !== 'undefined' ? window.location.hash : null), false);
    }

    let hadFocus = false;
    $effect(() => {
        if (!embedded) return;
        if (!focusId) {
            if (hadFocus && scope === 'features') selectedId = null;
            hadFocus = false;
            return;
        }
        hadFocus = true;
        selectedId = `${CPLUG_ITEM_PREFIX}${focusId}`;
        if (focusTab && isPaneTab(focusTab)) paneTab = focusTab;
    });

    /* could not be read */
    const limits = $derived([t(catalog ? 'plugins.page.limit.catalog' : 'plugins.page.limit.build_time'), t('plugins.page.limit.cplugs'), ...(catalog?.loadError ? [catalog.loadError] : [])]);

    function uiSlotsForPane(plugin: CplugItem): readonly CplugUiSlotRow[] {
        const seen = page.seenSheets[plugin.cplugId]?.ui_slots;
        if (seen && seen.length > 0) return seen;
        if (!plugin.uiContribute) return [];
        const granted = new Set(plugin.grantedUiSlots ?? plugin.uiSlotGrants ?? []);
        return Object.entries(plugin.uiContribute).map(([slot, entries]) => ({
            slot,
            count: Array.isArray(entries) ? entries.length : 1,
            risk: 'medium',
            reason: '',
            granted: granted.has(slot),
            needs_tick: true,
        }));
    }

    type OriginKind = 'builtin' | 'app' | 'agent' | 'local_dev';

    function originOf(item: ManagerItem): OriginKind {
        if (item.id.startsWith(CATALOG_ITEM_PREFIX)) {
            return (item as CatalogPluginItem).pluginKind === 'agent' ? 'agent' : 'app';
        }
        const plugin = item as CplugItem;
        if (plugin.pluginKind === 'agent-plugin') return 'agent';
        if (plugin.trustTier === 'local_dev' || plugin.tier === 'local' || (plugin.unverified && plugin.trustTier !== 'unverified_github')) return 'local_dev';
        if (isFeatureTier(plugin.tier) || plugin.trustTier === 'builtin') return 'builtin';
        return 'app';
    }

    function originBadge(origin: OriginKind): { readonly key: string; readonly tone: 'neutral' | 'accent' | 'info' } {
        if (origin === 'builtin') return { key: 'plugins.page.badge.builtin', tone: 'neutral' };
        if (origin === 'agent') return { key: 'plugins.page.badge.agent', tone: 'info' };
        if (origin === 'local_dev') return { key: 'plugins.page.badge.local_dev', tone: 'accent' };
        return { key: 'plugins.page.badge.app', tone: 'accent' };
    }

    function isEnabledItem(item: ManagerItem): boolean {
        if (item.enabled === true) return true;
        if (isCplugRow(item)) {
            return item.state === 'active';
        }
        return false;
    }

    const filters: ManagerFilter[] = $derived(
        scope === 'features'
            ? [
                  { id: 'on', label: t('plugins.page.filter.on'), on: featureChip === 'on', test: (item: ManagerItem) => item.enabled === true },
                  { id: 'off', label: t('plugins.page.filter.off'), on: featureChip === 'off', test: (item: ManagerItem) => item.enabled === false },
              ]
            : [
                  { id: 'all', label: t('plugins.page.filter.all'), on: pluginFilter === null, test: () => true },
                  { id: 'enabled', label: t('plugins.page.filter.enabled'), on: pluginFilter === 'enabled', test: isEnabledItem },
                  { id: 'builtin', label: t('plugins.page.filter.builtin'), on: pluginFilter === 'builtin', test: (item: ManagerItem) => originOf(item) === 'builtin' },
                  { id: 'app', label: t('plugins.page.filter.app'), on: pluginFilter === 'app', test: (item: ManagerItem) => originOf(item) === 'app' },
                  { id: 'agent', label: t('plugins.page.filter.agent'), on: pluginFilter === 'agent', test: (item: ManagerItem) => originOf(item) === 'agent' },
                  { id: 'local_dev', label: t('plugins.page.filter.local_dev'), on: pluginFilter === 'local_dev', test: (item: ManagerItem) => originOf(item) === 'local_dev' },
              ],
    );

    export function show(options?: { plugin?: string; settings?: boolean }): void {
        const link = options?.plugin ? { cplugId: options.plugin, settings: options.settings !== false } : pluginLinkOf(typeof window !== 'undefined' ? window.location.hash : null);
        if (!open) {
            opener = captureOpener();
            open = true;
            void loadAll();
        }
        applyLink(link);
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        selectedId = null;
        inspectedPluginId = null;
        actions.cancel();
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }
</script>

{#snippet settingsGear(item: ManagerItem)}
    {@const plugin = item as CplugItem}
    {#if scope !== 'features'}
        {@const badge = originBadge(originOf(item))}
        <div class="plug-card__badges" data-plugin-badges={plugin.cplugId}>
            <Tag tone={badge.tone} data-plugin-origin={originOf(item)}>{t(badge.key)}</Tag>
            {#if plugin.trustTier === 'unverified_github' || plugin.revoked || plugin.flagged || plugin.reviewVerdict === 'flagged' || plugin.reviewVerdict === 'clean'}
                {#if plugin.revoked}
                    <Tag tone="danger" data-plugin-revoked>{t(SKILL_KEYS.revokedBadge)}</Tag>
                {:else if plugin.flagged || plugin.reviewVerdict === 'flagged'}
                    <Tag tone="warn" data-plugin-verdict="flagged">{t(SKILL_KEYS.flaggedBadge)}</Tag>
                {:else if plugin.reviewVerdict === 'clean'}
                    <Tag tone="ok" data-plugin-verdict="clean">{t(SKILL_KEYS.cleanBadge)}</Tag>
                {/if}
                {#if plugin.trustTier === 'unverified_github'}
                    <Tag tone="warn" data-plugin-trust="unverified_github">{t('plugins.page.badge.unverified_github')}</Tag>
                {/if}
            {/if}
        </div>
    {/if}
    {#if plugin.state === 'needs_approval'}
        
        <Button
            size="sm"
            data-plugin-approval-mark={plugin.cplugId}
            aria-label={t('plugins.page.approval.open', { name: plugin.name })}
            title={t('plugins.page.approval.open', { name: plugin.name })}
            onclick={() => openSheet(plugin.id)}
        >
            {t('plugins.page.approval.mark')}
        </Button>
    {:else if plugin.thirdParty && plugin.state === 'active' && plugin.declared && canDrawGlance(plugin.unrenderedSurfaces)}
        
        <StatusChip cplugId={plugin.cplugId} installKey={plugin.installKey ?? null} declared={plugin.declared} unverified={plugin.unverified} {t} />
    {/if}
    {#if scope !== 'features' && plugin.thirdParty && plugin.pluginKind !== 'agent-plugin' && plugin.state !== 'removed'}
        <PluginHealthPill
            {plugin}
            snapshot={pluginsStore.inspectorOf(plugin.cplugId)}
            busy={ctl.toggles[plugin.id]?.busy === true}
            onLogs={inspectLogs}
            onRestart={(cplugId) => pluginsStore.restartPlugin(cplugId)}
            onPauseToggle={(cplugId, paused) => (paused ? pluginsStore.pausePlugin(cplugId) : pluginsStore.resumePlugin(cplugId))}
            {t}
        />
    {/if}
    {#if sideloads && plugin.unverified}<SideloadRowActions store={sideloads} name={plugin.cplugId} {t} />{/if}
    {#if hasPluginSettings(plugin)}
        
        <IconButton label={t('plugins.page.settings.open', { name: plugin.name })} variant="quiet" icon="gear" iconSize={14}
            data-plugin-settings-open={plugin.cplugId} onclick={() => applyLink({ cplugId: plugin.cplugId, settings: true })} />
    {/if}
{/snippet}

{#snippet paneStrip(item: ManagerItem)}
    {@const plugin = item as CplugItem}
    <PluginPaneStrip {plugin} busy={ctl.toggles[plugin.id]?.busy === true} onToggle={(next) => requestToggle(plugin.id, next)} {t} />
{/snippet}


{#snippet mediaBody(item: ManagerItem)}
    {#if item.icon}<Icon name={item.icon} size={32} />{:else}<span class="catalog-card__letter" aria-hidden="true">{Array.from(item.name || '?')[0]?.toUpperCase()}</span>{/if}
    {#if item.id.startsWith(CATALOG_ITEM_PREFIX)}<CardMediaImg sha={(item as CatalogPluginItem).mediaSha} />{/if}
{/snippet}


{#snippet cardExtraAny(item: ManagerItem)}
    {#if item.id.startsWith(CATALOG_ITEM_PREFIX) && catalog}
        {#if scope !== 'features'}
            {@const badge = originBadge(originOf(item))}
            {@const entry = item as CatalogPluginItem}
            <div class="plug-card__badges">
                <Tag tone={badge.tone} data-plugin-origin={originOf(item)}>{t(badge.key)}</Tag>
                {#if entry.revoked}
                    <Tag tone="danger" data-plugin-revoked>{t(SKILL_KEYS.revokedBadge)}</Tag>
                {:else if entry.flagged || entry.reviewVerdict === 'flagged'}
                    <Tag tone="warn" data-plugin-verdict="flagged">{t(SKILL_KEYS.flaggedBadge)}</Tag>
                {:else if entry.reviewVerdict === 'clean'}
                    <Tag tone="ok" data-plugin-verdict="clean">{t(SKILL_KEYS.cleanBadge)}</Tag>
                {/if}
            </div>
        {/if}
        <CatalogPluginFacts facts={catalog.facts((item as CatalogPluginItem).itemId)} {t} />
    {:else}
        {@render settingsGear(item)}
    {/if}
{/snippet}

{#snippet paneStripAny(item: ManagerItem)}
    {#if !item.id.startsWith(CATALOG_ITEM_PREFIX)}{@render paneStrip(item)}{/if}
{/snippet}


{#snippet cardAct(item: ManagerItem)}
    {#if catalog && item.id.startsWith(CATALOG_ITEM_PREFIX)}
        {@const entry = item as CatalogPluginItem}
        {@const act = catalog.act(entry.itemId)}
        {#if entry.revoked}
            <Button size="sm" data-act="revoked" disabled>{t(SKILL_KEYS.revokedBadge)}</Button>
        {:else if act.kind === 'update'}
            <Button variant="confirm" size="sm" data-act="update" disabled={page.toggles[item.id]?.busy === true} onclick={() => void page.runAct(item.id, () => catalog.update(entry.itemId))}>{t(SKILL_KEYS.actionUpdate)}</Button>
        {:else if act.kind === 'add'}
            <AddSplit projects={addProjects} haveGlobal={false} haveAnyProject={false} onAdd={(target, path) => void page.runAct(item.id, () => catalog.add(entry.itemId, target, path ?? null))} {t} />
        {/if}
    {/if}
{/snippet}

{#snippet headerActions()}
    {#if scope !== 'features'}
        <div class="plug-page__actions" bind:this={actionsEl}>
            {#if sideloads}
                <Button
                    variant="quiet"
                    size="sm"
                    bind:element={folderButton}
                    data-local-folder-sideload
                    onclick={() => (folderOpen = !folderOpen)}
                >
                    {t('plugins.page.sideload.load_folder')}
                </Button>
            {/if}
            <Button variant="secondary" data-build-plugin onclick={() => void openPluginStudio()}>
                {t('plugins.page.build_plugin_cta')}
            </Button>
            <Button variant="confirm" data-github-install onclick={openGithubSheet}>
                + {t('plugins.page.github.install_cta')}
            </Button>
        </div>
    {/if}
{/snippet}

{#snippet detailCatalog(item: ManagerItem)}
    {@const entry = item as CatalogPluginItem}
    <div class="plugin-catalog-pane">
        {#if entry.revoked}<RevokedBanner reason={entry.revocationReason} since={entry.revokedSince} {t} />{/if}
        {#if item.brief}<p>{item.brief}</p>{/if}
        {#if catalog}<CatalogPluginCredit credit={entry.credit} {t} />{/if}
        {#if catalog}<CatalogPluginFacts facts={catalog.facts(entry.itemId)} {t} />{/if}
    </div>
{/snippet}

{#snippet detailCplug(item: ManagerItem)}
    {@const plugin = item as CplugItem}
    <PluginPane
        {plugin}
        tab={paneTab}
        onTab={pickTab}
        asking={actions.pendingOff === plugin.id}
        busy={ctl.toggles[plugin.id]?.busy === true}
        error={ctl.toggles[plugin.id]?.error ?? null}
        onConfirmOff={() => actions.confirm()}
        onCancelOff={() => actions.cancel()}
        sheetStamp={page.seenSheets[plugin.cplugId] ? sheetStamp(page.seenSheets[plugin.cplugId]!) : ''}
        uiSlots={uiSlotsForPane(plugin)}
        onGrant={(ticks, slotTicks) => void actions.grantFromSheet(plugin, ticks, slotTicks)}
        {loadActivity}
        {purge}
        onPurged={() => void ctl.load()}
        onUninstall={page.ledgerRowOf(plugin) ? () => void page.uninstallFromPane(plugin) : undefined}
        onDisableAndUninstall={page.ledgerRowOf(plugin) ? () => void page.disableAndUninstallRevoked(plugin) : undefined}
        uninstalling={page.uninstallingId === plugin.id}
        uninstallError={page.uninstallErrors[plugin.id] ?? null}
        health={health?.rowOf(plugin)}
        canActHealth={health?.rowOf(plugin) ? canRun(health.rowOf(plugin)!, subjectOf(plugin)) : false}
        onHealth={() => { const row = health?.rowOf(plugin); if (row) void runHealthButton(row, subjectOf(plugin), healthDoors); }}
        inspector={pluginsStore.inspectorOf(plugin.cplugId)}
        onInspectLogs={inspectLogs}
        {t}
    />
{/snippet}


{#snippet healthZone()}
    <ClaudeCodeHealth
        rows={claudeRows}
        canAct={(row: HealthRow) => canRun(row, null)}
        onAct={(row: HealthRow) => void runHealthButton(row, null, healthDoors)}
        {t}
    />
{/snippet}

{#snippet detailAny(item: ManagerItem)}
    {#if item.id.startsWith(CATALOG_ITEM_PREFIX)}
        {@render detailCatalog(item)}
    {:else}
        {@render detailCplug(item)}
    {/if}
{/snippet}

{#if open}
    <ManagerFrame
        class="plug-page"
        title={t('plugins.page.title')}
        searchText={{ label: t('plugins.page.search.label'), placeholder: t('plugins.page.search.placeholder') }}
        {limits}
        limitsMode="tip"
        items={sorted}
        kit
        exclusiveFilters={scope === 'features'}
        actions={scope !== 'features' ? headerActions : undefined}
        sort={{
            label: t(MANAGER_KEYS.sortLabel),
            value: sortKey,
            options: [
                { value: 'featured', label: t('plugins.page.sort.featured') },
                { value: 'name', label: t('plugins.page.sort.name') },
                { value: 'state', label: t('plugins.page.sort.state') },
            ],
        }}
        onSort={(next) => (sortKey = next === 'state' || next === 'name' ? next : 'featured')}
        status={ctl.status}
        {query}
        onQuery={(next) => (query = next)}
        {filters}
        onFilter={(id, on) => {
            if (scope === 'features') {
                featureChip = on ? (id as 'on' | 'off') : null;
            } else {
                pluginFilter = id === 'all' ? null : on ? (id as typeof pluginFilter) : null;
            }
        }}
        onClearFilters={() => {
            featureChip = null;
            pluginFilter = null;
        }}
        viewKey={scope === 'features' ? 'features' : 'plugins'}
        defaultView="grid"
        warezCards
        warezKind="plugin"
        cardAct={catalog ? cardAct : undefined}
        {mediaBody}
        {selectedId}
        cardExtra={catalog ? cardExtraAny : settingsGear}
        detailKicker={t('plugins.page.pane.kicker')}
        detailBar={catalog ? paneStripAny : paneStrip}
        detailFill
        detail={catalog ? detailAny : detailCplug}
        onSelect={(id) => {
            const resolved = resolveSwarmSelectionTarget(id, ctl.items);
            if (!resolved) return;
            const target = resolved.target;
            if (actions.pendingOff !== target) actions.cancel();
            selectedId = target;
            tellHost();
        }}
        onToggle={requestToggle}
        toggles={{ ...ctl.toggles, ...page.toggles }}
        zone={claudeRows.length > 0 ? healthZone : undefined}
        onRetry={() => void ctl.load()}
        onClose={embedded ? undefined : close}
        emptyText={t('plugins.page.empty')}
        {embedded}
        {t}
    >
    </ManagerFrame>

    {#if folderOpen && sideloads}
        <AnchoredPopup label={t('plugins.page.sideload.load_folder')} anchor={folderButton} onClose={() => (folderOpen = false)}>
            <SideloadLoadForm
                mode="folder"
                {t}
                onFolder={(path, name, consent) => sideloads.loadFolder(path, name, consent)}
                onGit={(request) => sideloads.loadGit(request)}
                onDone={() => {
                    folderOpen = false;
                    void loadAll();
                }}
            />
        </AnchoredPopup>
    {/if}

    <PluginInstallSheet
        open={installSheet !== null}
        mode={installSheet?.mode ?? 'github'}
        card={installSheet?.card ?? null}
        item={installSheet?.item ?? null}
        host={installSheet?.mode === 'catalog' ? browserCatalogHost() : null}
        projects={sheetProjects}
        initialScope={installSheet?.initialScope ?? null}
        initialProject={installSheet?.initialProject ?? null}
        runtimeActive={sheetRuntimeActive}
        {loadSheet}
        onClose={closeInstallSheet}
        onDone={finishInstallSheet}
        {t}
    />
{/if}

<style>
    @layer components {
        .plug-page__actions {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-1-5);
        }

        .plug-card__badges {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-1);
        }

        .plugin-catalog-pane {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-2);
            padding: var(--oc-space-3);
            color: var(--oc-text-secondary);
        }

        :global([data-plugin-approval-mark]) {
            --_btn-edge: var(--oc-yellow);
            --_btn-ink: var(--oc-yellow);
            align-self: flex-start;
            min-height: 0;
            padding: 1px 6px;
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
        }

        :global([data-act='update']) {
            min-height: 44px;
        }
    }
</style>
