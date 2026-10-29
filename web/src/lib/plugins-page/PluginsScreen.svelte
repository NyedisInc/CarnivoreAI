
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import StatusChip from '../cplug-ui/StatusChip.svelte';
    import { createManagerController } from '../manager-frame/manager-controller.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { ManagerAdapter, ManagerFilter, ManagerItem, ManagerToggleState } from '../manager-frame/types';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import PluginPane from './PluginPane.svelte';
    import PluginPaneStrip from './PluginPaneStrip.svelte';
    import { createPluginActions } from './plugin-actions.svelte';
    import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
    import { openModal, openModalCount } from '../modal';
    import InstallSheet from '../catalog/InstallSheet.svelte';
    import { browserCatalogHost } from '../catalog/catalog';
    import type { CardView } from '../catalog/card';
    import type { SheetOutcome } from '../catalog/types';
    import DeveloperZone from './DeveloperZone.svelte';
    import SideloadRowActions from './SideloadRowActions.svelte';
    import { createSideloadStore } from './sideload-store.svelte';
    import CardMediaImg from '../catalog/CardMediaImg.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import IconButton from '../base/IconButton.svelte';
    import Button from '../base/Button.svelte';
    import AddSplit from '../catalog/AddSplit.svelte';
    import { addProjectsOf } from '../catalog/add-projects';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import CatalogPluginFacts from './CatalogPluginFacts.svelte';
    import CatalogPluginCredit from './CatalogPluginCredit.svelte';
    import { CATALOG_ITEM_PREFIX, createCatalogPlugins, type CatalogPluginItem, type CatalogPlugins } from './catalog-plugins.svelte';
    import { readTab, writeTab } from '../../opscenter/ui/tab-memory';
    import { grantCplug, readSheet, sheetStamp, type GrantOptions } from './cplug-grant';
    import { CPLUG_ITEM_PREFIX, createCplugsAdapter, listActivity, type ActivityRow, type CplugItem, type CplugSheet, type CplugsAdapter } from './cplugs-adapter';
    import { PANE_TAB_MEMORY, PANE_TABS, isPaneTab, type PaneTab, type PurgePrice } from './plugin-pane';
    import { hasPluginSettings, pluginLinkOf, type PluginLink } from './plugin-settings-link';

    import { isBuiltinPlugin } from '../catalog/app-own';
    import { uninstallPlugin, uninstallableRow } from './plugin-uninstall';

    interface Props {
        adapter?: ManagerAdapter;
        t?: Translate;
        embedded?: boolean;
        focusId?: string | null;
        focusTab?: string | null;
        onSelect?: (cplugId: string, tab: string) => void;
        onChanged?: () => void;
        storeOnly?: boolean;
        grant?: (cplugId: string, ticks: string[], options: GrantOptions) => Promise<unknown>;
        loadSheet?: (cplugId: string) => Promise<CplugSheet>;
        loadActivity?: (cplugId: string) => Promise<ActivityRow[]>;
        purge?: (cplugId: string, confirmToken?: string) => Promise<PurgePrice>;
        catalog?: CatalogPlugins | null;
    }

    const { adapter, t = appT, embedded = false, focusId = null, focusTab = null, onSelect: onPick, onChanged, storeOnly = false, grant = (id, ticks, options) => grantCplug(id, ticks, t, undefined, undefined, options), loadSheet = readSheet, loadActivity = listActivity, purge, catalog: catalogProp }: Props = $props();

    let seenSheets = $state<Record<string, CplugSheet>>({});

    // svelte-ignore state_referenced_locally
    const pageAdapter: ManagerAdapter & Partial<CplugsAdapter> = adapter ?? createCplugsAdapter(t);
    // svelte-ignore state_referenced_locally
    const ctl = createManagerController(pageAdapter, t(MANAGER_KEYS.errorTitle));
    // svelte-ignore state_referenced_locally
    const actions = createPluginActions({ ctl, adapter: pageAdapter, grant, seenSheet: (id) => seenSheets[id], onAsk: (id) => (selectedId = id) });
    // svelte-ignore state_referenced_locally
    const sideloads = adapter ? null : createSideloadStore(undefined, () => void ctl.load());

    let seenSig: string | null = null;
    $effect(() => {
        const sig = ctl.items.map((row) => `${row.id}:${row.enabled ?? ''}`).join('|');
        const before = seenSig;
        seenSig = sig;
        if (before !== null && before !== sig) onChanged?.();
    });

    async function openCatalogSheet(card: CardView, prefill: { scope: 'project'; projectPath: string } | { scope: 'global'; projectPath: null }): Promise<SheetOutcome | null> {
        if (openModalCount() > 0) return null;
        return (await openModal(InstallSheet as never, { card, host: browserCatalogHost(), t, prefill } as never)) as SheetOutcome | null;
    }

    // svelte-ignore state_referenced_locally
    const catalog: CatalogPlugins | null =
        catalogProp !== undefined ? catalogProp : adapter ? null : createCatalogPlugins({ host: browserCatalogHost(), t, openSheet: openCatalogSheet });
    const catalogItems = $derived<CatalogPluginItem[]>(catalog ? catalog.items() : []);
    let catalogToggles = $state<Record<string, ManagerToggleState>>({});

    async function toggleCatalog(id: string, next: boolean): Promise<void> {
        const item = catalogItems.find((row) => row.id === id);
        if (!catalog || !item || catalogToggles[id]?.busy) return;
        catalogToggles = { ...catalogToggles, [id]: { busy: true, error: null } };
        try {
            await catalog.setEnabled(item.itemId, next);
            if (next && !catalog.items().some((row) => row.id === id)) void ctl.load();
            catalogToggles = { ...catalogToggles, [id]: { busy: false, error: null } };
        } catch (error) {
            catalogToggles = { ...catalogToggles, [id]: { busy: false, error: error instanceof Error ? error.message : t('plugins.page.catalog.failed') } };
        }
    }

    async function runAct(id: string, run: () => Promise<void>): Promise<void> {
        if (catalogToggles[id]?.busy) return;
        catalogToggles = { ...catalogToggles, [id]: { busy: true, error: null } };
        try {
            await run();
            catalogToggles = { ...catalogToggles, [id]: { busy: false, error: null } };
        } catch (error) {
            catalogToggles = { ...catalogToggles, [id]: { busy: false, error: error instanceof Error ? error.message : t('plugins.page.catalog.failed') } };
        }
    }

    const addProjects = $derived(addProjectsOf(catalog?.projects ?? [], null));

    let uninstallingId = $state<string | null>(null);
    let uninstallErrors = $state<Record<string, string | null>>({});

    function ledgerRowOf(plugin: CplugItem) {
        return catalog && plugin.thirdParty && plugin.publisher ? uninstallableRow(catalog.ledger(), `${plugin.publisher}/${plugin.cplugId}`) : undefined;
    }

    async function uninstallFromPane(plugin: CplugItem): Promise<void> {
        const row = ledgerRowOf(plugin);
        if (!row || !catalog || uninstallingId !== null || openModalCount() > 0) return;
        uninstallingId = plugin.id;
        uninstallErrors = { ...uninstallErrors, [plugin.id]: null };
        try {
            const result = await uninstallPlugin(row, plugin.name, catalog, t);
            uninstallErrors = { ...uninstallErrors, [plugin.id]: result.error };
            if (result.done) await Promise.all([catalog.load(), ctl.load()]);
        } finally {
            uninstallingId = null;
        }
    }

    async function loadAll(): Promise<void> {
        void catalog?.load();
        await ctl.load();
    }

    function requestToggle(id: string, next: boolean): void {
        if (id.startsWith(CATALOG_ITEM_PREFIX)) {
            void toggleCatalog(id, next);
            return;
        }
        actions.request(id, next);
    }

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');
    let chip = $state<'on' | 'off' | null>(null);
    let selectedId = $state<string | null>(null);
    let sortKey = $state<'featured' | 'name' | 'state'>('featured');
    const sorted = $derived.by(() => {
        const builtins = ctl.items.filter((row) => !storeOnly || !isBuiltinPlugin((row as CplugItem).tier));
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

    let sheetRead = 0;
    $effect(() => {
        const item = ctl.items.find((row) => row.id === selectedId) as CplugItem | undefined;
        if (paneTab !== 'permissions' || !item?.consentRequired || (item.state !== 'disabled' && item.state !== 'needs_approval')) return;
        const id = item.cplugId;
        const mine = ++sheetRead;
        loadSheet(id).then(
            (sheet) => { if (mine === sheetRead) seenSheets = { ...seenSheets, [id]: sheet }; },
            () => { if (mine === sheetRead) { const { [id]: _gone, ...rest } = seenSheets; seenSheets = rest; } },
        );
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

    $effect(() => {
        if (!embedded || !focusId) return;
        selectedId = `${CPLUG_ITEM_PREFIX}${focusId}`;
        if (focusTab && isPaneTab(focusTab)) paneTab = focusTab;
    });

    /* could not be read */
    const limits = $derived([t(catalog ? 'plugins.page.limit.catalog' : 'plugins.page.limit.build_time'), t('plugins.page.limit.cplugs'), ...(catalog?.loadError ? [catalog.loadError] : [])]);

    const projectOptions = $derived([
        { value: '', label: t('plugins.page.catalog.project.none') },
        ...(catalog?.projects ?? []).flatMap((project) => {
            const path = project.path || project.root;
            return path ? [{ value: path, label: project.name || path }] : [];
        }),
    ]);

    const filters: ManagerFilter[] = $derived([
        { id: 'on', label: t('plugins.page.filter.on'), on: chip === 'on', test: (item: ManagerItem) => item.enabled === true },
        { id: 'off', label: t('plugins.page.filter.off'), on: chip === 'off', test: (item: ManagerItem) => item.enabled === false },
    ]);

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
    {:else if plugin.thirdParty && plugin.state === 'active' && plugin.declared}
        
        <StatusChip cplugId={plugin.cplugId} installKey={plugin.installKey ?? null} declared={plugin.declared} unverified={plugin.unverified} {t} />
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
        {#if act.kind === 'update'}
            <Button variant="confirm" size="sm" data-act="update" disabled={catalogToggles[item.id]?.busy === true} onclick={() => void runAct(item.id, () => catalog.update(entry.itemId))}>{t(SKILL_KEYS.actionUpdate)}</Button>
        {:else if act.kind === 'add'}
            <AddSplit projects={addProjects} haveGlobal={false} haveAnyProject={false} onAdd={(target, path) => void runAct(item.id, () => catalog.add(entry.itemId, target, path ?? null))} {t} />
        {/if}
    {/if}
{/snippet}

{#snippet toolbar()}
    {#if catalog}
        <FacetSelect
            id="plugins-project"
            label={t('plugins.page.catalog.project.label')}
            value={catalog.projectPath ?? ''}
            options={projectOptions}
            onChange={(next) => void catalog.pick(next === '' ? null : next)}
        />
    {/if}
{/snippet}


{#snippet developerZone()}
    <DeveloperZone {t} {sideloads} />
{/snippet}

{#snippet detailCatalog(item: ManagerItem)}
    <div class="plugin-catalog-pane">
        {#if item.brief}<p>{item.brief}</p>{/if}
        {#if catalog}<CatalogPluginCredit credit={(item as CatalogPluginItem).credit} {t} />{/if}
        {#if catalog}<CatalogPluginFacts facts={catalog.facts((item as CatalogPluginItem).itemId)} {t} />{/if}
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
        sheetStamp={seenSheets[plugin.cplugId] ? sheetStamp(seenSheets[plugin.cplugId]!) : ''}
        onGrant={(ticks) => void actions.grantFromSheet(plugin, ticks)}
        {loadActivity}
        {purge}
        onPurged={() => void ctl.load()}
        onUninstall={ledgerRowOf(plugin) ? () => void uninstallFromPane(plugin) : undefined}
        uninstalling={uninstallingId === plugin.id}
        uninstallError={uninstallErrors[plugin.id] ?? null}
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
        exclusiveFilters
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
        onFilter={(id, on) => (chip = on ? (id as 'on' | 'off') : null)}
        onClearFilters={() => (chip = null)}
        viewKey="plugins"
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
            if (actions.pendingOff !== id) actions.cancel();
            selectedId = id;
            tellHost();
        }}
        onToggle={requestToggle}
        toggles={{ ...ctl.toggles, ...catalogToggles }}
        toolbar={catalog ? toolbar : undefined}
        zone={catalog && !adapter ? developerZone : undefined}
        onRetry={() => void ctl.load()}
        onClose={embedded ? undefined : close}
        emptyText={t('plugins.page.empty')}
        {embedded}
        {t}
    >
    </ManagerFrame>
{/if}

<style>
    @layer components {
        .plugin-catalog-pane {
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 12px;
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
