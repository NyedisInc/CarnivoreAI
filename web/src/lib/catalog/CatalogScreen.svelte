
<script lang="ts">
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { openModalCount } from '../modal';
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import Page from '../../opscenter/ui/Page.svelte';
    import CatalogDetail from './CatalogDetail.svelte';
    import { displayKind } from './kind-display';
    import CatalogRows from './CatalogRows.svelte';
    import CatalogToolbar from './CatalogToolbar.svelte';
    import CatalogFilterRail from './CatalogFilterRail.svelte';
    import WarezMenu from './menu/WarezMenu.svelte';
    import WarezPane from './menu/WarezPane.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { nodeLabel } from './menu/model';
    import { HOME_NODE, MENU_KINDS, nodeHash, type MenuKind, type MenuNode } from './menu/route';
    import { createMenuData } from './menu/sources.svelte';
    import { newestItems } from './census';
    import { withState } from './filter-groups';
    import ViewToggle from '../manager-frame/ViewToggle.svelte';
    import { openSignInModal } from '../carnivore-account/open-signin';
    import { CATALOG_SESSION_EVENT } from '../drawer-hud/catalog-account.svelte';
    import CatalogPhoneBar from './CatalogPhoneBar.svelte';
    import WarezActs from './WarezActs.svelte';
    import WarezTools from './WarezTools.svelte';
    import WarezStatusLine from './WarezStatusLine.svelte';
    import WarezCensus from './WarezCensus.svelte';
    import { loadInstallCounts } from './census';
    import type { Snippet } from 'svelte';
    import SearchField from '../../opscenter/ui/SearchField.svelte';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import type { ManagerView } from '../manager-frame/view-memory';
    import { readPageView, writePageView } from '../../opscenter/ui/page-view';
    import { isPressable, isTyping, keyAction } from './keys';
    import { sortCards, type SortKey } from './sort';
    import { readSort, writeSort } from './sort-store';
    import PluginInstallSheet from '../plugins-page/PluginInstallSheet.svelte';
    import { pluginsStore } from '../plugins/store.svelte';
    import {
        applyCatalogLedgerChange,
        catalogProjectOptions,
        deriveCatalogRuntimeActive,
        dispatchCatalogKeyAction,
        openLegacyInstallSheet,
        runCatalogPluginUpdateIfDue,
        runQuickAddForCard,
        stepCatalogSelection,
        type CatalogPluginSheetState,
        type CatalogSheetPrefill,
    } from './catalog-plugin-sheet';
    import { browserCatalogHost, type CatalogHost } from './catalog';
    import { openPublishPage } from './publish-entry';
    import { provideReadonly } from './readonly';
    import TrustLine from './TrustLine.svelte';
    import { revealOnPhone } from './phone-reveal';
    import { createCatalogData } from './catalog-data.svelte';
    import { addProjectsOf } from './add-projects';
    import type { ProjectRow } from '../sessions/types';
    import { installedDescTotal } from './cost';
    import type { CardView } from './card';
    import {
        NO_FILTERS,
        isNarrowed,
        kindsOf,
        visibleCards,
        type CatalogFilters,
    } from './filter';
    import type {
        CatalogItem,
        CatalogMeta,
        InstalledItem,
        SheetOutcome,
    } from './types';

    export const SEARCH_DEBOUNCE_MS = 150;

    const VIEW_KEY = 'skills';

    interface Props {
        host?: CatalogHost;
        t?: Translate;
        title?: string;
        embedded?: boolean;
        active?: boolean;
        onClose?: () => void;
        signedIn?: boolean | null;
        meta?: CatalogMeta | null;
        searchSlot?: Snippet | undefined;
        barSlot?: Snippet | undefined;
        controlsSlot?: Snippet | undefined;
        highlights?: Snippet;
        bands?: boolean;
        readonly?: boolean;
    }

    let {
        host = browserCatalogHost(),
        t = reactiveT,
        title,
        embedded = false,
        active = true,
        signedIn = $bindable(null),
        meta = $bindable(null),
        searchSlot = $bindable(undefined),
        barSlot = $bindable(undefined),
        controlsSlot = $bindable(undefined),
        highlights,
        bands = false,
        readonly = false,
    }: Props = $props();

    // svelte-ignore state_referenced_locally
    provideReadonly(readonly);

    // svelte-ignore state_referenced_locally
    const data = createCatalogData(host, t);
    // svelte-ignore state_referenced_locally
    const menu = createMenuData(data, t);

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let typed = $state('');
    let query = $state('');
    let filters = $state<CatalogFilters>({ ...NO_FILTERS });
    /* the warez menu */
    let node = $state<MenuNode>(HOME_NODE);
    let phoneView = $state<'menu' | 'page'>('menu');
    let selectedId = $state<string | null>(null);
    let sortKey = $state<SortKey>(readSort());
    /* the downloaded sort */
    let installs = $state<ReadonlyMap<string, number>>(new Map());
    $effect(() => {
        const ids = data.items.map((item) => item?.id).filter((id): id is string => !!id);
        if (!(bands || sortKey === 'downloaded') || !open || ids.length === 0) return;
        let cancelled = false;
        void loadInstallCounts(host, ids).then((counts) => { if (!cancelled) installs = counts; });
        return () => { cancelled = true; };
    });
    let view = $state<ManagerView>(readPageView(VIEW_KEY, 'cards') === 'cards' ? 'grid' : 'list');
    let searchInput = $state<HTMLInputElement | undefined>();
    let wantedId = $state<string | null>(null);
    let notFoundId = $state<string | null>(null);
    let debounce: ReturnType<typeof setTimeout> | null = null;
    let opener: HTMLElement | null = null;
    $effect(() => {
        void signedIn;
        window.dispatchEvent(new CustomEvent(CATALOG_SESSION_EVENT));
    });
    let currentProject = $state<string | null>(null);

    let projectRows = $state<ProjectRow[]>([]);

    const addProjects = $derived(addProjectsOf(projectRows, currentProject));

    const shown = $derived(
        sortCards(visibleCards(data.cards, filters, query, data.installed), sortKey, data.items, installs),
    );
    const shownUntrusted = $derived(
        visibleCards(data.untrustedCards, filters, query, data.installed),
    );
    const kinds = $derived(kindsOf(data.cards));
    const narrowed = $derived(isNarrowed(filters, query));
    const browsing = $derived(bands && !isNarrowed({ ...filters, kind: null }, query));
    const shelfShown = $derived(!bands || (browsing && filters.kind === null && shown.some((card) => card.isLoadout && card.id)));
    const packless = $derived(bands && shelfShown ? shown.filter((card) => !card.isLoadout) : shown);
    const sources = $derived(menu.sources);
    /* the census band */
    const newestIds = $derived(new Set(newestItems(data.items).map((item) => item.id)));
    const gridShown = $derived(bands && node.scope === 'store' && node.page === 'newest' ? packless.filter((card) => !!card.id && newestIds.has(card.id)) : packless);
    const menuOn = $derived(bands && !embedded);
    const installedPane = $derived(menuOn && (node.scope === 'installed' || node.scope === 'publish' || (node.scope === 'look' && node.page !== 'updates')));
    const selected = $derived(
        selectedId
            ? (shown.find((card) => card.id === selectedId) ??
               data.untrustedCards.find((card) => card.id === selectedId) ??
               null)
            : null,
    );
    const reading = $derived(selected && !installedPane ? selected : null);

    export function show(options: { kind?: string; item?: string; node?: MenuNode; home?: boolean } = {}): void {
        if (options.home) {
            applyNode(HOME_NODE);
            phoneView = 'menu';
        } else if (options.node) {
            applyNode(options.node);
        } else if (options.kind) {
            const kind = displayKind(options.kind)!;
            if ((MENU_KINDS as readonly string[]).includes(kind)) applyNode({ scope: 'store', page: 'kind', kind: kind as MenuKind });
            else filters = { ...filters, kind };
            phoneView = 'page';
        }
        if (options.item) {
            wantedId = options.item;
            notFoundId = null;
            phoneView = 'page';
        }
        if (open) return;
        const focused = typeof document !== 'undefined' ? document.activeElement : null;
        opener = focused instanceof HTMLElement ? focused : null;
        open = true;
        begin();
    }

    function begin(): void {
        void data.refresh();
        void data.openRefresh();
        host.currentProjectPath().then(
            (path) => { currentProject = path; },
            () => { currentProject = null; },
        );
        host.listProjects().then(
            (rows) => { projectRows = rows; },
            () => { projectRows = []; },
        );
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        selectedId = null;
        wantedId = null;
        notFoundId = null;
        if (opener && typeof document !== 'undefined' && document.contains(opener)) {
            opener.focus();
        }
        opener = null;
    }

    export function refresh(): void {
        void data.refresh();
    }

    export function isOpen(): boolean {
        return open;
    }

    function setView(next: ManagerView): void {
        view = next;
        writePageView(VIEW_KEY, next === 'grid' ? 'cards' : 'ledger');
    }

    const signInAct = $derived(signedIn === false && !readonly ? () => void openSignInModal({ feature: 'rate', src: 'catalog' }) : undefined);

    const searchInTitle = $derived(viewport.narrow);

    $effect(() => {
        if (!embedded) return;
        const offer = searchInTitle && active;
        searchSlot = offer ? searchField : undefined;
        barSlot = offer ? pageBar : undefined;
        controlsSlot = offer ? flipControl : undefined;
    });

    function onQuery(next: string): void {
        typed = next;
        if (debounce !== null) clearTimeout(debounce);
        debounce = setTimeout(() => {
            query = typed;
            debounce = null;
        }, SEARCH_DEBOUNCE_MS);
    }

    function clearFilters(): void {
        if (debounce !== null) {
            clearTimeout(debounce);
            debounce = null;
        }
        typed = '';
        query = '';
        filters = { ...NO_FILTERS };
    }

    function applyNode(next: MenuNode): void {
        if (next.scope === 'store' && next.page === 'item') {
            node = HOME_NODE;
            filters = { ...NO_FILTERS };
            wantedId = next.id;
            notFoundId = null;
        } else {
            node = next;
            if (next.scope === 'store' || (next.scope === 'look' && next.page === 'updates')) {
                const kind = next.scope === 'store' && next.page === 'kind' ? next.kind : null;
                const updates = next.page === 'updates';
                filters = updates ? withState({ ...NO_FILTERS }, 'updates') : { ...NO_FILTERS, kind };
                selectedId = null;
                notFoundId = null;
            }
        }
        phoneView = 'page';
    }

    function navigate(next: MenuNode): void {
        applyNode(next);
        try {
            const hash = nodeHash(next);
            if (globalThis.location && globalThis.location.hash !== hash) globalThis.history.pushState(null, '', hash);
        } catch {
        }
    }

    function backFromPage(): void {
        if (node.scope === 'installed' && node.page === 'item') navigate({ scope: 'installed', page: 'kind', kind: node.kind });
        else {
            phoneView = 'menu';
            try {
                if (globalThis.location && globalThis.location.hash !== '#warez') globalThis.history.pushState(null, '', '#warez');
            } catch {
            }
        }
    }

    let pluginSheet = $state<CatalogPluginSheetState | null>(null);

    async function openSheet(card: CardView, prefill: CatalogSheetPrefill | null = null): Promise<void> {
        if (openModalCount() > 0 || pluginSheet !== null) return;
        if (card.isCplug || card.isPlugin) {
            if (await runCatalogPluginUpdateIfDue({ card, prefill, host, data, t })) return;
            const safePrefill =
                card.isCplug && !card.isPlugin
                    ? { scope: 'global' as const, projectPath: null }
                    : prefill;
            data.send(card.id, { kind: 'verify' });
            pluginSheet = { card, prefill: safePrefill };
            return;
        }
        data.send(card.id, { kind: 'verify' });
        await openLegacyInstallSheet({ card, host, data, t, prefill });
    }

    async function addTo(card: CardView, target: 'global' | 'project', projectPath: string | null = null): Promise<void> {
        if (!card.id || openModalCount() > 0 || pluginSheet !== null) return;
        if (card.isCplug || card.isPlugin) {
            const safeScope = card.isCplug && !card.isPlugin ? 'global' : target;
            const safePath = safeScope === 'project' ? projectPath : null;
            await openSheet(card, { scope: safeScope, projectPath: safePath });
            return;
        }
        await runQuickAddForCard({
            card,
            target,
            projectPath,
            host,
            data,
            onSheetRequired: (prefill) => openSheet(card, prefill),
        });
    }

    function onLedgerChange(id: string, row: InstalledItem | null, installId: string | null = null): void {
        applyCatalogLedgerChange(data, id, row, installId);
    }

    function onKeydown(event: KeyboardEvent): void {
        if (!open || !active) return;
        if (openModalCount() > 0 || pluginSheet !== null) return;
        const action = keyAction(event, isTyping(event.target), isPressable(event.target));
        if (!action) return;
        event.preventDefault();
        dispatchCatalogKeyAction(action, {
            searchInput,
            selectedId,
            moveSelection: (step) =>
                stepCatalogSelection({
                    shown,
                    shownUntrusted,
                    selectedId,
                    setSelectedId: (id) => { selectedId = id; },
                    step,
                }),
        });
    }

    $effect(() => {
        if (!open || !wantedId || data.loading) return;
        const id = wantedId;
        wantedId = null;
        const known = [...data.cards, ...data.untrustedCards].some((card) => card.id === id);
        if (known) clearFilters();
        selectedId = known ? id : null;
        notFoundId = known ? null : id;
    });

    $effect(() => {
        if (!open || !menuOn) return;
        return menu.start();
    });

    $effect(() => {
        if (!embedded) return;
        meta = {
            visible: shown.length + shownUntrusted.length,
            total: data.cards.length + data.untrustedCards.length,
            asOf: data.index?.as_of ?? null,
            degraded: data.index?.degraded === true,
        };
    });

    // svelte-ignore state_referenced_locally
    let wasActive = active;
    $effect(() => {
        const now = active;
        if (now && !wasActive && open && embedded) void data.refresh();
        wasActive = now;
    });

    async function readSession(): Promise<void> {
        try {
            const next = await host.catalogSession();
            signedIn = next.signed_in === true;
        } catch {
            if (signedIn === null) signedIn = false;
        }
    }

    onMount(() => {
        void readSession();
        if (embedded) begin();
        window.addEventListener(CATALOG_SESSION_EVENT, readSession);
        if (typeof document !== 'undefined') {
            document.addEventListener('keydown', onKeydown);
        }
        return () => {
            window.removeEventListener(CATALOG_SESSION_EVENT, readSession);
            if (debounce !== null) clearTimeout(debounce);
            if (typeof document !== 'undefined') {
                document.removeEventListener('keydown', onKeydown);
            }
        };
    });
</script>

{#snippet detailPane(card: CardView, onClose?: () => void)}
            <CatalogDetail
                card={card}
                item={data.items.find((entry) => entry && entry.id === card.id) ?? null}
                installed={card.id ? (data.installed[card.id] ?? []) : []}
                costTotal={installedDescTotal(data.items, data.installed)}
                palette={card.id ? (data.palettes.get(card.id) ?? null) : null}
                rowState={data.stateFor(card.id)}
                {host}
                {t}
                onInstall={() => void openSheet(card)}
                onAdd={(target, projectPath) => void addTo(card, target, projectPath ?? null)}
                projects={addProjects}
                {onLedgerChange}
                signedIn={signedIn === true}
                {onClose}
            />
{/snippet}


{#snippet readingPane()}
    {#if reading}<div class="screen__detail" use:revealOnPhone>{@render detailPane(reading)}</div>{/if}
{/snippet}

{#snippet catalogDetail(id: string)}
    {@const card = data.cards.find((c) => c.id === id)}
    {#if card}{@render detailPane(card, () => navigate({ scope: 'installed', page: 'kind', kind: card.kind as MenuKind }))}{/if}
{/snippet}


{#snippet searchField()}
    <SearchField
        value={typed}
        onInput={onQuery}
        ariaLabel={t(SKILL_KEYS.searchLabel)}
        placeholder={t('warez.search.placeholder')}
        bind:input={searchInput}
    />
{/snippet}

{#snippet pageBar()}
    <CatalogToolbar {filters} {kinds} {t} onFilters={(next) => { filters = next; }} />
{/snippet}

{#snippet statusLine(wrap: boolean)}
    <WarezStatusLine index={data.index} loading={data.loading} {wrap} {t} />
{/snippet}

{#snippet phoneStatus()}
    {@render statusLine(true)}
{/snippet}

{#snippet topOfScroll()}
    
    {#if searchInTitle}
        <CatalogPhoneBar
            {sortKey}
            refreshing={data.refreshing}
            onRefresh={() => void data.refreshIndex()}
            onPublish={() => openPublishPage()}
            onSort={(next) => { sortKey = next; writeSort(next); }}
            {t}
        />
    {/if}
    {#if browsing}<WarezCensus items={data.items} kind={filters.kind} {installs} {t} />{/if}
    {#if highlights}{@render highlights()}{/if}
{/snippet}


{#snippet sideNav()}
    {#if menuOn}
        <WarezMenu {sources} {node} find={typed} onClearFind={() => onQuery('')} onNavigate={navigate} {t} />
    {:else}
        <CatalogFilterRail {filters} {kinds} {t} onFilters={(next) => { filters = next; }} onPublish={() => openPublishPage()} />
    {/if}
{/snippet}

{#snippet flipControl()}
    <ViewToggle {view} onView={setView} {t} shelf />
{/snippet}

{#if open}
    <!-- the reading pane -->
    {#snippet pageActions()}
        {@render statusLine(false)}
        {#if !installedPane}<WarezTools {sortKey} onSort={(next) => { sortKey = next; writeSort(next); }} {view} onView={setView} {t} />{/if}
        <WarezActs refreshing={data.refreshing} onRefresh={() => void data.refreshIndex()} onPublish={() => openPublishPage()} showPublish={menuOn || false} {t} />
    {/snippet}

    
    <Page
        class="cat"
        title={title ?? t(SKILL_KEYS.screenTitle)}
        icon="floppy-525"
        {embedded}
        onClose={embedded || readonly ? undefined : close}
        closeLabel={t(MANAGER_KEYS.close)}
        frame="nav"
        scroll="self"
        side={searchInTitle ? undefined : sideNav}
        sideLabel={menuOn ? nodeLabel(node, sources, t) : (title ?? t(SKILL_KEYS.screenTitle))}
        actions={searchInTitle ? undefined : pageActions}
        find={searchInTitle ? undefined : searchField}
        search={!embedded && searchInTitle && !(menuOn && phoneView === 'menu') ? searchField : undefined}
        backIcon="chevron-left"
        omnibar="kit"
        controls={!embedded && searchInTitle && !(menuOn && phoneView === 'menu') ? flipControl : undefined}
        bar={searchInTitle && !embedded && !menuOn && !installedPane && !selected ? pageBar : undefined}
        detail={reading ? readingPane : undefined}
        detailTitle={reading?.headline ?? undefined}
        detailFill
        onDetailClose={() => { selectedId = null; }}
    >
        <div class="cat-col">
        {#if notFoundId}
            <p class="screen__notfound" role="status">
                {t(BROWSE_KEYS.itemNotFound, { id: notFoundId })}
            </p>
        {/if}

        {#if menuOn && searchInTitle && phoneView === 'menu'}
            
            <div class="screen__menu"><WarezMenu {sources} {node} phone onNavigate={navigate} {t} /></div>
        {:else}
            {#if menuOn && searchInTitle}
                <div class="screen__back">
                    <button type="button" class="screen__backbtn" data-back onclick={backFromPage}>
                        <Icon name="chevron-left" size={14} />
                        <span>{node.scope === 'installed' && node.page === 'item' ? nodeLabel({ scope: 'installed', page: 'kind', kind: node.kind }, sources, t) : t('warez.title')}</span>
                    </button>
                    <h1 class="screen__backtitle">{nodeLabel(node, sources, t)}</h1>
                </div>
            {/if}
        <div class="screen__body" class:screen__body--flush={menuOn}>
            {#if installedPane && (node.scope === 'installed' || node.scope === 'look' || node.scope === 'publish')}
                <div class="screen__installed"><WarezPane {node} {sources} {t} onNavigate={navigate} onChanged={() => void menu.reload()} {catalogDetail} /></div>
            {:else}
            <CatalogRows
                {data}
                shown={gridShown}
                {shownUntrusted}
                {narrowed}
                shelf={shelfShown}
                palettes={data.palettes}
                status={phoneStatus}
                onSignIn={signInAct}
                {selectedId}
                {t}
                {view}
                highlights={topOfScroll}
                kind={filters.kind}
                onSelect={(id) => { selectedId = id; notFoundId = null; }}
                onSheet={(card) => void openSheet(card)}
                onClearFilters={clearFilters}
                projects={addProjects}
                onAdd={(card, target, projectPath) => void addTo(card, target, projectPath ?? null)}
            />
            {/if}

        </div>
        {/if}
        {#if readonly}<TrustLine index={data.index} {t} />{/if}
        </div>
    </Page>

    <PluginInstallSheet
        open={pluginSheet !== null}
        mode="catalog"
        card={pluginSheet?.card ?? null}
        {host}
        projects={catalogProjectOptions(projectRows)}
        initialScope={pluginSheet?.card.isCplug && !pluginSheet?.card.isPlugin ? 'global' : (pluginSheet?.prefill?.scope ?? null)}
        initialProject={pluginSheet?.card.isCplug && !pluginSheet?.card.isPlugin ? null : (pluginSheet?.prefill?.projectPath ?? currentProject)}
        runtimeActive={deriveCatalogRuntimeActive(pluginsStore.rows)}
        onClose={() => {
            const id = pluginSheet?.card.id ?? null;
            pluginSheet = null;
            data.send(id, { kind: 'dismiss' });
        }}
        onDone={() => {
            const id = pluginSheet?.card.id ?? null;
            pluginSheet = null;
            data.send(id, { kind: 'install' });
            data.send(id, { kind: 'installed' });
            void data.refresh();
        }}
        {t}
    />
{/if}

<style>
    :global(.cat) {
        --cat-ground: var(--oc-ground-page);
        --cat-panel: var(--oc-ground-panel);
        --cat-raised: var(--oc-ground-raised);
        --cat-line: var(--oc-line-rule);
        --cat-line-quiet: var(--oc-line-faint);
        --cat-text: var(--oc-text-primary);
        --cat-muted: var(--oc-text-secondary);
        --cat-faint: var(--oc-text-muted);
        --cat-action: var(--oc-orange);
        --cat-action-edge: var(--oc-orange-dim);
        --cat-action-wash: var(--oc-orange-tint);
        --cat-attention: var(--oc-yellow);
        --cat-failure: var(--oc-coral);
        --cat-failure-wash: color-mix(in srgb, var(--oc-coral) 12%, var(--oc-ground-panel));
        --cat-mono: var(--font-mono);
        --cat-gutter: 16px;
    }

    .cat-col {
        display: flex;
        flex-direction: column;
        min-width: 0;
        min-height: 0;
    }

    .screen__notfound {
        margin: 0 var(--cat-gutter);
        padding: 6px 8px;
        border-left: 2px solid var(--cat-attention);
        background: var(--cat-raised);
        color: var(--cat-text);
        font-size: 12px;
    }

    .screen__body {
        flex: 1;
        display: grid;
        grid-template-columns: 1fr;
        min-height: 0;
        width: min(100%, 1680px);
        margin-inline: auto;
    }

    .screen__body--flush {
        width: 100%;
        margin-inline: 0;
    }

    .screen__menu {
        flex: 1;
        min-height: 0;
        overflow-y: auto;
    }

    .screen__back {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: none;
        min-height: 52px;
        padding: 0 12px;
        background: var(--oc-ground-titlerow);
        box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
        font-family: var(--font-mono);
    }

    .screen__backbtn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 44px;
        padding: 0 10px 0 4px;
        border: 1px solid transparent;
        border-radius: 2px;
        background: transparent;
        color: var(--oc-text-primary);
        font: inherit;
        font-size: 13px;
        cursor: pointer;
    }

    .screen__backtitle {
        flex: 1 1 0;
        min-width: 0;
        margin: 0;
        overflow: hidden;
        color: var(--oc-orange);
        font-size: var(--oc-fs-title, 12px);
        font-weight: 400;
        letter-spacing: var(--oc-tracking-title, 0.8px);
        text-overflow: ellipsis;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .screen__installed {
        min-width: 0;
        min-height: 0;
        overflow-y: auto;
    }

    .screen__detail {
        display: flex;
        flex-direction: column;
        min-height: 100%;
    }

    @media (max-width: 767px) {
        :global(.cat) {
            --cat-gutter: 12px;
        }

        .screen__body {
            flex: none;
        }

        .screen__installed {
            overflow: visible;
        }
    }
</style>
