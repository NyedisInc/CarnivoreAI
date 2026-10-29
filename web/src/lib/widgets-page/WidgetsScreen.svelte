<!-- the reading pane -->
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import Page from '../../opscenter/ui/Page.svelte';
    import PageToolbar, { type ToolbarFacet } from '../../opscenter/ui/PageToolbar.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import SearchField from '../../opscenter/ui/SearchField.svelte';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import { createManagerController } from '../manager-frame/manager-controller.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { ManagerAdapter } from '../manager-frame/types';
    import './widgets-page.css';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { railStores } from '../session-rail/rail-store.svelte';
    import type { ItemSettingsController } from '../item-settings/item-settings-controller.svelte';
    import { createWidgetsAdapter, type WidgetItem } from './widgets-adapter';
    import PlacesBody from './PlacesBody.svelte';
    import WidgetPane from './WidgetPane.svelte';
    import { PLACES } from './places';
    import { boardList } from './places-state.svelte';
    import { resetView, setPlace, view } from './places-view.svelte';
    import { resetBars } from './places-writes';
    import { showToast } from './undo-toast';

    interface Props {
        adapter?: ManagerAdapter;
        t?: Translate;
        embedded?: boolean;
        settingsFor?: (id: string) => ItemSettingsController;
        previews?: boolean;
    }

    const { adapter, t = appT, embedded = false, settingsFor, previews = true }: Props = $props();

    // svelte-ignore state_referenced_locally
    const ctl = createManagerController(adapter ?? createWidgetsAdapter(t), t(MANAGER_KEYS.errorTitle));

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');
    let selectedId = $state<string | null>(null);
    let openMenu = $state<((anchor: HTMLElement, id: string) => void) | undefined>();

    resetView();
    // svelte-ignore state_referenced_locally
    if (embedded) void ctl.load();

    $effect(() => {
        if (!open) return;
        railStores.side.start();
        railStores.bottom.start();
    });

    export function show(): void {
        if (open) return;
        opener = captureOpener();
        resetView();
        open = true;
        void ctl.load();
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        selectedId = null;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    /* the reading pane */
    function escape(event: KeyboardEvent): void {
        if (event.key !== 'Escape' || selectedId === null || event.defaultPrevented || document.querySelector('.session-row-menu')) return;
        const field = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement ? event.target : null;
        if (field && field.value !== '') return;
        event.preventDefault();
        event.stopPropagation();
        selectedId = null;
    }
    $effect(() => {
        if (!open) return;
        document.addEventListener('keydown', escape, true);
        return () => document.removeEventListener('keydown', escape, true);
    });

    function help(): void {
        showToast({ kind: 'saved', text: t('widgets.places.help'), surface: t('widgets.page.title'), ms: 8000 });
    }

    const sortOptions = $derived([
        { value: 'group', label: t('widgets.places.sort.group') },
        { value: 'name', label: t('widgets.places.sort.name') },
    ]);
    const fitsOptions = $derived([
        { value: 'any', label: t('widgets.places.facet.any') },
        ...PLACES.map((def) => ({ value: def.id, label: t(`widgets.places.${def.id}.short`) })),
    ]);
    const showOptions = $derived([
        { value: 'all', label: t('widgets.places.facet.show_all') },
        { value: 'fits', label: t('widgets.places.facet.show_fits') },
    ]);
    const boards = $derived(boardList());
    const boardOptions = $derived(boards.map((one) => ({ value: one.id, label: one.name })));
    const facets = $derived.by<ToolbarFacet[]>(() => {
        const list: ToolbarFacet[] = [{ id: 'sort', label: t('widgets.places.sort.label'), value: view.sort, options: sortOptions }, { id: 'fits', label: t('widgets.places.facet.fits'), value: view.place, options: fitsOptions }];
        if (view.place !== 'any') list.push({ id: 'show', label: t('widgets.places.facet.show'), value: view.show, options: showOptions });
        if (boardOptions.length > 1) list.push({ id: 'board', label: t('widgets.places.facet.board'), value: view.board, options: boardOptions });
        return list;
    });

    function facet(id: string, next: string): void {
        if (id === 'sort') view.sort = next === 'name' ? 'name' : 'group';
        else if (id === 'fits') setPlace(next as typeof view.place);
        else if (id === 'show') view.show = next === 'fits' ? 'fits' : 'all';
        else if (id === 'board') view.board = next;
    }
    const narrow = $derived(viewport.narrow && !embedded);
</script>

{#snippet searchBox()}
    <span class="wp-find">
        <SearchField value={query} onInput={(next) => (query = next)} ariaLabel={t(MANAGER_KEYS.searchLabel)} placeholder={t('widgets.page.filter_placeholder')} />
        {#if query !== ''}<button type="button" class="wp-find__clear" data-k="clear-find" aria-label={t(MANAGER_KEYS.clear)} onclick={() => (query = '')}><Icon name="close" size={10} /></button>{/if}
    </span>
{/snippet}

{#snippet toolbar(withSearch: boolean)}
    <PageToolbar
        showSearch={withSearch}
        search={withSearch ? searchBox : undefined}
        {facets}
        onFacet={facet}
        showView={false}
        view="cards"
        onView={() => {}}
        {t}
    />
{/snippet}

{#snippet barToolbar()}{@render toolbar(false)}{/snippet}

{#if open}
    <Page
        class="wp-screen"
        title={t('widgets.page.title')}
        ariaLabel={t('widgets.page.label')}
        {embedded}
        onClose={embedded ? undefined : close}
        search={narrow ? searchBox : undefined}
        bar={narrow ? barToolbar : undefined}
    >
        {#snippet sub()}{#if !narrow}{@render toolbar(true)}{/if}{/snippet}
        {#snippet actions()}
            <button type="button" class="oc-btn oc-btn--sm" data-k="reset-bars" title={t('widgets.places.reset.title')} onclick={() => void resetBars(t)}>{t('widgets.places.reset.label')}</button>
            <button type="button" class="oc-btn oc-btn--sm wp-help" data-k="help" title={t('widgets.places.help.title')} aria-label={t('widgets.places.help.title')} onclick={help}>{t('widgets.places.help.label')}</button>
        {/snippet}
        <PlacesBody
            items={ctl.items as readonly WidgetItem[]}
            {query}
            status={ctl.status}
            {t}
            {selectedId}
            onOpen={(id) => (selectedId = id)}
            live={previews}
            onRetry={() => void ctl.load()}
            onClear={() => (query = '')}
            limits={[t('widgets.page.limit.build_time')]}
            bind:openMenu
        >
            {#snippet detail()}
                {@const item = ctl.items.find((one) => one.id === selectedId)}
                {#if item}
                    {#key item.id}
                        <WidgetPane
                            item={item as WidgetItem}
                            {t}
                            toggle={ctl.toggles[item.id]}
                            onToggle={(id, next) => void ctl.toggle(id, next)}
                            onMenu={(anchor, id) => openMenu?.(anchor, id)}
                            onClose={() => (selectedId = null)}
                            {settingsFor}
                            {previews}
                        />
                    {/key}
                {/if}
            {/snippet}
        </PlacesBody>
    </Page>
{/if}
