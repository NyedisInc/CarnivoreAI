<!-- the detail pane -->
<script lang="ts">
    import type { Snippet } from 'svelte';
    import { tick } from 'svelte';
    import '../ledger/ledger-chrome.css';
    import './manager-frame.css';
    import './manager-card.css';
    import './manager-card-rich.css';
    import type { Translate } from '../sessions/types';
    import InfoTip from '../info-tip/InfoTip.svelte';
    import IconButton from '../base/IconButton.svelte';
    import Page from '../../opscenter/ui/Page.svelte';
    import { isInset } from '../../opscenter/ui/page-inset';
    import { clearToasts } from '../../opscenter/ui/detail-clearance';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import SearchField from '../../opscenter/ui/SearchField.svelte';
    import PageToolbar from '../../opscenter/ui/PageToolbar.svelte';
    import type { FacetOption } from '../../opscenter/ui/FacetSelect.svelte';
    import ManagerCard from './ManagerCard.svelte';
    import ManagerItemActions from './ManagerItemActions.svelte';
    import ViewToggle from './ViewToggle.svelte';
    import { readView, writeView, type ManagerView } from './view-memory';
    import { groupItems, isNarrowed, isSwitchable, MANAGER_KEYS, visibleItems } from './manager-model';
    import type { ManagerActionState, ManagerFilter, ManagerItem, ManagerStatus, ManagerToggleState } from './types';

    interface Props {
        title: string;
        label?: string;
        items: readonly ManagerItem[];
        status: ManagerStatus;
        query: string;
        onQuery: (next: string) => void;
        filters?: readonly ManagerFilter[];
        onFilter?: (id: string, on: boolean) => void;
        onClearFilters?: () => void;
        layout?: 'grid' | 'list';
        warezCards?: boolean;
        warezKind?: string;
        cardAct?: Snippet<[ManagerItem]>;
        viewKey?: string;
        defaultView?: ManagerView;
        /* the detail pane */
        selectedId?: string | null;
        /* the detail pane */
        onSelect?: (id: string | null) => void;
        onToggle?: (id: string, next: boolean) => void;
        toggles?: Readonly<Record<string, ManagerToggleState>>;
        onRetry?: () => void;
        onClose?: () => void;
        emptyText?: string;
        embedded?: boolean;
        t: Translate;
        onExport?: (id: string) => void;
        onRemove?: (id: string) => void;
        itemActions?: Readonly<Record<string, ManagerActionState>>;
        removed?: string | null;
        onInstall?: () => void;
        installLabel?: string;
        limits?: readonly string[];
        limitsMode?: 'strip' | 'tip';
        actions?: Snippet;
        toolbar?: Snippet;
        cardExtra?: Snippet<[ManagerItem]>;
        cardMedia?: boolean;
        mediaBody?: Snippet<[ManagerItem]>;
        onStar?: (id: string) => void;
        kit?: boolean;
        countBeside?: boolean;
        exclusiveFilters?: boolean;
        sort?: { readonly label: string; readonly value: string; readonly options: readonly FacetOption[] };
        onSort?: (value: string) => void;
        detail?: Snippet<[ManagerItem]>;
        detailKicker?: string;
        detailBar?: Snippet<[ManagerItem]>;
        detailFill?: boolean;
        body?: Snippet;
        top?: Snippet;
        searchable?: boolean;
        /* something else */
        searchText?: { label: string; placeholder: string };
        searchInput?: HTMLInputElement | undefined;
        groups?: readonly string[];
        groupOf?: (item: ManagerItem) => string;
        groupHead?: Snippet<[string, readonly ManagerItem[]]>;
        showCount?: boolean;
        lede?: string;
        class?: string;
    }

    let {
        title,
        label,
        items,
        status,
        query,
        onQuery,
        filters = [],
        onFilter,
        onClearFilters,
        layout: layoutProp = 'grid',
        warezCards = false,
        warezKind = '',
        cardAct,
        viewKey,
        defaultView = 'grid',
        selectedId = null,
        onSelect,
        onToggle,
        toggles = {},
        onRetry,
        onClose,
        showCount = true,
        emptyText,
        embedded = false,
        t,
        onExport,
        onRemove,
        itemActions = {},
        removed = null,
        onInstall,
        installLabel,
        limits = [],
        limitsMode = 'strip',
        actions: actionsSnippet,
        toolbar,
        cardExtra,
        cardMedia = false,
        mediaBody,
        onStar,
        kit = false,
        countBeside = false,
        exclusiveFilters = false,
        sort,
        onSort,
        detail,
        detailKicker,
        detailBar,
        detailFill = false,
        body,
        top,
        searchable = true,
        searchText,
        searchInput = $bindable(),
        groups,
        groupOf,
        groupHead,
        lede,
        class: className = '',
    }: Props = $props();

    // svelte-ignore state_referenced_locally
    const inset = isInset();
    const searchInTitle = $derived(searchable && viewport.narrow && !embedded && !inset);
    const hasPageActions = $derived(!!onInstall || !!actionsSnippet);
    const actionsInBar = $derived(searchInTitle && hasPageActions);
    let frameWidth = $state(typeof window !== 'undefined' ? window.innerWidth : 390);
    $effect(() => {
        if (!root || typeof ResizeObserver === 'undefined') return;
        const watch = new ResizeObserver(([entry]) => {
            if (entry) frameWidth = entry.contentRect.width;
        });
        watch.observe(root);
        return () => watch.disconnect();
    });
    const filterRoom = $derived(frameWidth - 32 - 46 - 150 - 8 - (viewKey ? 52 : 0));
    const filtersInBar = $derived(
        searchInTitle && filters.length > 0 && filters.reduce((sum, f) => sum + Math.max(44, f.label.length * 7 + 16), 0) <= filterRoom,
    );
    const flipInBar = $derived(searchInTitle && !!viewKey);
    const kitBar = $derived(kit && !searchInTitle);
    const countInBar = $derived(countBeside && kitBar && inset);
    const stateFacet = $derived(
        exclusiveFilters && filters.length > 0
            ? [
                  {
                      id: 'state',
                      label: t(MANAGER_KEYS.facetState),
                      value: filters.find((f) => f.on)?.id ?? '',
                      options: [{ value: '', label: t(MANAGER_KEYS.facetAll) }, ...filters.map((f) => ({ value: f.id, label: f.label }))],
                  },
              ]
            : [],
    );

    function pickState(value: string): void {
        for (const f of filters) if (f.on && f.id !== value) onFilter?.(f.id, false);
        if (value !== '') onFilter?.(value, true);
    }
    const barHasControls = $derived(
        !!lede || (filters.length > 0 && !filtersInBar) || !!toolbar || (!!viewKey && !flipInBar) || actionsInBar,
    );

    const uid = `mgr-${Math.random().toString(36).slice(2, 9)}`;

    // svelte-ignore state_referenced_locally
    let view = $state<ManagerView>(viewKey ? readView(viewKey, defaultView) : defaultView);
    const layout = $derived(viewKey ? view : layoutProp);

    function setView(next: ManagerView): void {
        view = next;
        if (viewKey) writeView(viewKey, next);
    }

    let root: HTMLDivElement | undefined = $state();
    let detailTitle: HTMLHeadingElement | undefined = $state();

    const shown = $derived(visibleItems(items, query, filters));
    const narrowed = $derived(isNarrowed(query, filters));
    const grouped = $derived(
        groupHead && groupOf && groups ? groupItems(shown, groups, groupOf, narrowed) : null,
    );
    const selected = $derived(
        detail && selectedId !== null ? (items.find((item) => item.id === selectedId) ?? null) : null,
    );
    const countText = $derived(
        !showCount || status.kind !== 'ready'
            ? ''
            : narrowed
              ? t(MANAGER_KEYS.countFiltered, { shown: shown.length, total: items.length })
              : t(MANAGER_KEYS.count, { count: items.length }),
    );

    let focusedFor: string | null = null;
    $effect(() => {
        const id = selected?.id ?? null;
        if (id !== null && id !== focusedFor && detailTitle) detailTitle.focus();
        focusedFor = id;
    });

    async function closeDetail(): Promise<void> {
        const id = selected?.id ?? null;
        onSelect?.(null);
        await tick();
        if (id === null || !root) return;
        const card = Array.from(root.querySelectorAll<HTMLElement>('[data-item-id]')).find(
            (element) => element.dataset.itemId === id,
        );
        card?.querySelector<HTMLElement>('.mgr-card__open')?.focus();
    }

    /* the detail pane */
    function onKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Escape' || event.defaultPrevented) return;
        if (searchInput && event.target === searchInput && query !== '') {
            event.preventDefault();
            onQuery('');
            return;
        }
        if (selected) {
            event.preventDefault();
            void closeDetail();
        }
    }

    function clearAll(): void {
        onQuery('');
        onClearFilters?.();
    }
</script>

{#snippet pageActions()}
    {#if onInstall}
        <button type="button" class="oc-btn oc-btn--confirm" data-mgr-install onclick={onInstall}>
            {installLabel ?? t(MANAGER_KEYS.install)}
        </button>
    {/if}
    {#if actionsSnippet}{@render actionsSnippet()}{/if}
{/snippet}

{#snippet searchField()}
        <SearchField
            value={query}
            onInput={onQuery}
            ariaLabel={searchText?.label ?? t(MANAGER_KEYS.searchLabel)}
            placeholder={searchText?.placeholder ?? t(MANAGER_KEYS.searchPlaceholder)}
            bind:input={searchInput}
        />
{/snippet}

{#snippet chips()}
    <div class="oc-page__chips" role="group" aria-label={t(MANAGER_KEYS.filtersLabel)}>
        {#each filters as filter (filter.id)}
            <button
                type="button"
                class="oc-chip"
                aria-pressed={filter.on}
                onclick={() => onFilter?.(filter.id, !filter.on)}>{filter.label}</button
            >
        {/each}
    </div>
{/snippet}

{#snippet barControls()}
    {#if filtersInBar}{@render chips()}{/if}
    {#if flipInBar}<ViewToggle {view} onView={setView} {t} />{/if}
{/snippet}

{#snippet kitExtras()}{#if !exclusiveFilters && filters.length > 0}{@render chips()}{/if}{#if toolbar}{@render toolbar()}{/if}{/snippet}

{#snippet pageBar()}
        {#if lede}<p class="oc-page__lede" data-page-lede>{lede}</p>{/if}
        {#if kitBar}
            <PageToolbar
                search={searchField}
                facets={stateFacet}
                onFacet={(_id, value) => pickState(value)}
                endLead={countInBar ? pageSub : undefined}
                extras={toolbar || (!exclusiveFilters && filters.length > 0) ? kitExtras : undefined}
                {sort}
                {onSort}
                showView={!!viewKey}
                view={view === 'grid' ? 'cards' : 'ledger'}
                onView={(next) => setView(next === 'cards' ? 'grid' : 'list')}
                {t}
            />
        {:else}
        {#if !searchInTitle}{@render searchField()}{/if}
        {#if filters.length > 0 && !filtersInBar}{@render chips()}{/if}
        {#if toolbar}<div class="oc-page__tools">{@render toolbar()}</div>{/if}
        {#if actionsInBar}<div class="oc-page__tools oc-page__tools--end">{@render pageActions()}</div>{/if}
        {#if viewKey && !flipInBar}<ViewToggle {view} onView={setView} {t} />{/if}
        {/if}
{/snippet}

{#snippet pageSub()}
    {#if label}<span class="oc-label">{label}</span>{/if}
    {#if countText}<span class="oc-titlebar__count">{countText}</span>{/if}
    <InfoTip text={limits.join(' ')} label={t(MANAGER_KEYS.limitsLabel)} />
{/snippet}

{#snippet pageNotes()}
    {#if removed}<p class="oc-notice" role="status" data-mgr-removed>{t(MANAGER_KEYS.removed, { name: removed })}</p>{/if}
    {#if limits.length > 0 && limitsMode === 'strip'}
        <div class="oc-page__limits" data-mgr-limits>
            <span class="oc-label">{t(MANAGER_KEYS.limitsLabel)}</span>
            {#each limits as limit (limit)}<p class="oc-notice oc-notice--muted">{limit}</p>{/each}
        </div>
    {/if}
{/snippet}

<Page
    bind:root
    class="pledger mgr {className}"
    {embedded}
    {title}
    label={countInBar ? undefined : label}
    count={countInBar ? undefined : countText}
    sub={limits.length > 0 && limitsMode === 'tip' && !countInBar ? pageSub : undefined}
    {onClose}
    closeLabel={t(MANAGER_KEYS.close)}
    onkeydown={onKeydown}
    actions={hasPageActions && !actionsInBar ? pageActions : undefined}
    search={searchInTitle ? searchField : undefined}
    controls={searchInTitle && (filtersInBar || flipInBar) ? barControls : undefined}
    bar={searchable && !(searchInTitle && !barHasControls) ? pageBar : undefined}
    notes={(limits.length > 0 && limitsMode === 'strip') || removed ? pageNotes : undefined}
>
    <div class="oc-page__body" class:oc-page__body--reading={selected !== null}>
        <div class="oc-page__scroll">
            <div class="oc-page__main">
                {#if top}{@render top()}{/if}
                {#if body}
                    {@render body()}
                {:else if status.kind === 'loading'}
                    <p class="oc-page__state" role="status">{t(MANAGER_KEYS.loading)}</p>
                {:else if status.kind === 'error'}
                    <div class="oc-page__error" role="alert">
                        <p class="oc-page__error-title">{t(MANAGER_KEYS.errorTitle)}</p>
                        <p class="oc-page__error-detail">{status.message}</p>
                        {#if onRetry}
                            <button type="button" class="oc-btn" onclick={onRetry}>
                                {t(MANAGER_KEYS.errorRetry)}
                            </button>
                        {/if}
                    </div>
                {:else if grouped && grouped.length > 0}
                    {#each grouped as group (group.id)}
                        <section class="oc-page__group" data-group={group.id}>
                            {@render groupHead?.(group.id, group.items)}
                            {#if group.items.length > 0}
                                <ul class="oc-page__items" class:oc-page__items--list={layout === 'list'} class:oc-card-grid={layout !== 'list'} class:warez-grid={warezCards && layout !== 'list'}>
                                    {#each group.items as item (item.id)}
                                        <li class="oc-page__item">
                                            <ManagerCard
                                                {item}
                                                selected={selected?.id === item.id}
                                                switchable={isSwitchable(item, onToggle !== undefined)}
                                                toggle={toggles[item.id]}
                                                {t}
                                                onOpen={detail && onSelect ? (id) => onSelect(id) : undefined}
                                                {onToggle}
                                                extra={cardExtra}
                                                media={cardMedia}
                                                {mediaBody}
                                                warez={warezCards}
                                                {warezKind}
                                                act={cardAct}
                                                {onStar}
                                                rowSelect={layout === 'list'}
                                            />
                                        </li>
                                    {/each}
                                </ul>
                            {/if}
                        </section>
                    {/each}
                {:else if shown.length === 0}
                    <div class="oc-page__empty pl-panel">
                        {#if narrowed && items.length > 0}
                            <p class="oc-page__empty-text">{t(MANAGER_KEYS.emptyFiltered)}</p>
                            <button type="button" class="oc-btn" onclick={clearAll}>
                                {t(MANAGER_KEYS.clear)}
                            </button>
                        {:else}
                            <p class="oc-page__empty-text">{emptyText ?? t(MANAGER_KEYS.empty)}</p>
                        {/if}
                    </div>
                {:else}
                    <ul class="oc-page__items" class:oc-page__items--list={layout === 'list'} class:oc-card-grid={layout !== 'list'} class:warez-grid={warezCards && layout !== 'list'}>
                        {#each shown as item (item.id)}
                            <li class="oc-page__item">
                                <ManagerCard
                                    {item}
                                    selected={selected?.id === item.id}
                                    switchable={isSwitchable(item, onToggle !== undefined)}
                                    toggle={toggles[item.id]}
                                    {t}
                                    onOpen={detail && onSelect ? (id) => onSelect(id) : undefined}
                                    {onToggle}
                                    extra={cardExtra}
                                                media={cardMedia}
                                                {mediaBody}
                                                warez={warezCards}
                                                {warezKind}
                                                act={cardAct}
                                                {onStar}
                                    rowSelect={layout === 'list'}
                                />
                            </li>
                        {/each}
                    </ul>
                {/if}
            </div>
        </div>

        {#if selected && detail}
            <section class="oc-page__detail" aria-labelledby="{uid}-detail" use:clearToasts>
                <div class="pl-titlebar mgr__detail-bar">
                    <h2 class="pl-title mgr__detail-title" class:mgr__detail-title--kicked={!!detailKicker} id="{uid}-detail" tabindex="-1" bind:this={detailTitle}>
                        {#if detailKicker}<span class="mgr__detail-kicker">{detailKicker}</span>
                            <span class="mgr__detail-name">{selected.name}</span>{:else}{selected.name}{/if}
                    </h2>
                    {#if detailBar}{@render detailBar(selected)}{/if}
                    {#if detailKicker}
                        <IconButton label={t(MANAGER_KEYS.detailBack)} variant="quiet" icon="arrow-left" iconSize={14} onclick={() => void closeDetail()} />
                    {:else}
                        <button type="button" class="oc-btn oc-btn--ghost" onclick={() => void closeDetail()}>
                            {t(MANAGER_KEYS.detailBack)}
                        </button>
                    {/if}
                </div>
                <div class="oc-page__detail-body" class:mgr__detail-body--fill={detailFill}>
                    {@render detail(selected)}
                    <ManagerItemActions item={selected} {onExport} {onRemove} progress={itemActions[selected.id]} {t} />
                </div>
            </section>
        {/if}
    </div>
</Page>
