
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import { onMount } from 'svelte';
    import { clearToasts } from '../../opscenter/ui/detail-clearance';
    import ThemeCard from './ThemeCard.svelte';
    import '../catalog/warez-card.css';
    import ThemeDetail from './ThemeDetail.svelte';
    import BuildYourOwn from './BuildYourOwn.svelte';
    import { openPublishPage } from '../catalog/publish-entry';
    import { themeFavorites } from './favorites.svelte';
    import { applyGlobalTheme } from './global-theme';
    import { previewPalette, type PreviewPalette } from './preview-palette';
    import { THEME_FILTERS, filterCounts, visibleThemes, type ThemeFilter } from './themes-page-model';
    import { openCatalogScreen } from '../catalog/screen-host';
    import { themes } from '../../opscenter/api';
    import Page from '../../opscenter/ui/Page.svelte';
    import SearchField from '../../opscenter/ui/SearchField.svelte';
    import { Button, Segmented } from '../base';
    import { t } from '../i18n/index.svelte';

    import { isBuiltinTheme } from '../catalog/app-own';

    interface Props {
        embedded?: boolean;
        focusId?: string | null;
        onLibrary?: () => void;
        onSelect?: (id: string) => void;
        onChanged?: () => void;
        storeOnly?: boolean;
    }
    const { embedded = false, focusId = null, onLibrary, onSelect, onChanged, storeOnly = false }: Props = $props();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let filter = $state<ThemeFilter>('all');
    let query = $state('');
    let selectedId = $state<string | null>(null);
    let panel = $state<'theme' | 'guide'>('theme');
    let sheetOpen = $state(false);
    let pageTheme = $state<string | null>(null);
    let searchInput = $state<HTMLInputElement | undefined>();
    let bodyEl = $state<HTMLElement | undefined>();
    const NARROW_BODY_PX = 720;

    const all = $derived((themes.status === 'ok' ? (themes.data ?? []) : []).filter((m) => !storeOnly || !isBuiltinTheme(m.source)));
    const palettes = $derived(new Map<string, PreviewPalette>(all.map((m) => [m.id, previewPalette(m)])));
    const favoriteIds = $derived(themeFavorites.ids);
    const shown = $derived(visibleThemes(all, filter, query, favoriteIds));
    const counts = $derived(filterCounts(all, favoriteIds));
    const selected = $derived(all.find((m) => m.id === selectedId) ?? null);
    const activeName = $derived(all.find((m) => m.id === pageTheme)?.name ?? pageTheme ?? '');

    const notice = $derived.by((): string | null => {
        if (themes.status === 'loading') return t('opscenter.themes.loading');
        if (themes.status === 'signed-out') return t('opscenter.themes.signed_out');
        if (themes.status === 'unavailable') return t('opscenter.themes.unavailable');
        if (themes.status === 'error') return themes.error ?? t('opscenter.themes.error');
        if (!all.length) return t('opscenter.themes.none');
        if (shown.length) return null;
        if (filter === 'favorites' && !query) return t('themes.page.empty.favorites');
        return t('themes.page.empty.search');
    });

    export function show(): void {
        if (open) return;
        opener = captureOpener();
        open = true;
        themeFavorites.start();
        void themes.refresh(true);
        pageTheme = document.documentElement.dataset.theme ?? null;
        if (!selectedId) selectedId = pageTheme;
    }

    export function close(): void {
        if (!open) return;
        open = false;
        sheetOpen = false;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    function select(id: string): void {
        selectedId = id;
        panel = 'theme';
        sheetOpen = true;
        onSelect?.(id);
    }

    function apply(id: string): void {
        applyGlobalTheme(id);
    }

    function toggleGuide(): void {
        panel = panel === 'guide' ? 'theme' : 'guide';
        sheetOpen = panel === 'guide' || selectedId !== null;
    }

    function openLibrary(): void {
        if (onLibrary) onLibrary();
        else openCatalogScreen({ kind: 'theme' });
    }

    function inspectorReplacesGrid(): boolean {
        return bodyEl !== undefined && bodyEl.clientWidth > 0 && bodyEl.clientWidth < NARROW_BODY_PX;
    }

    function onKeydown(event: KeyboardEvent): void {
        if (!open) return;
        const typing = event.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
        if (event.key === '/' && !typing) {
            event.preventDefault();
            searchInput?.focus();
        } else if (event.key === 'Escape') {
            if (sheetOpen && inspectorReplacesGrid()) sheetOpen = false;
        }
    }

    // svelte-ignore state_referenced_locally
    if (embedded) {
        themeFavorites.start();
        void themes.refresh(true);
    }
    $effect(() => {
        if (embedded && focusId) {
            selectedId = focusId;
            panel = 'theme';
            sheetOpen = true;
        }
    });

    onMount(() => {
        const read = (): void => {
            const next = document.documentElement.dataset.theme ?? null;
            const moved = pageTheme !== null && next !== pageTheme;
            pageTheme = next;
            if (embedded && !selectedId) selectedId = pageTheme;
            if (embedded && moved) onChanged?.();
        };
        read();
        const observer = new MutationObserver(read);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        document.addEventListener('keydown', onKeydown);
        return () => {
            observer.disconnect();
            document.removeEventListener('keydown', onKeydown);
        };
    });
</script>

{#snippet pageSub()}
    <span class="oc-titlebar__count">{counts.all} {t('themes.page.stat.installed')}</span>
    <span class="oc-titlebar__count">{counts.favorites} {t('themes.page.stat.favorites')}</span>
{/snippet}

{#snippet pageBar()}
    <SearchField
        bind:input={searchInput}
        value={query}
        onInput={(next) => (query = next)}
        placeholder={t('themes.page.search')}
        keyshortcuts="/"
    />
    <Segmented
        label={t('themes.page.filter.label')}
        bind:value={filter}
        options={THEME_FILTERS.filter((option) => !storeOnly || option !== 'builtin').map((option) => ({ value: option, label: `${t(`themes.page.filter.${option}`)} ${counts[option]}`, attrs: { 'data-theme-filter': option } }))}
    />
    <div class="oc-page__tools">
        <Button onclick={openLibrary}>{t('themes.page.library')}</Button>
        <Button aria-pressed={panel === 'guide'} onclick={toggleGuide}>
            {t('themes.page.guide.open')}
        </Button>
        <span class="themes-active">
            <span class="oc-label">{t('themes.page.stat.active')}</span>
            {#if pageTheme && activeName}
                <Button
                    variant="quiet"
                    size="sm"
                    data-themes-now
                    aria-label={t('themes.page.stat.active.open', { name: activeName })}
                    onclick={() => pageTheme && select(pageTheme)}
                >{activeName}</Button>
            {:else}
                <span class="themes-now">{t('themes.page.fact.unset')}</span>
            {/if}
        </span>
    </div>
{/snippet}

{#if open}
    <Page
        class="themes-screen"
        title={t('themes.page.title')}
        onClose={embedded ? undefined : close}
        {embedded}
        closeLabel={t('themes.page.back')}
        sub={pageSub}
        bar={pageBar}
    >
        <div class="oc-page__body themes-body" class:themes-body--detail={sheetOpen} bind:this={bodyEl}>
            <div class="oc-page__scroll">
                <section class="oc-page__main" aria-label={t('themes.page.grid')}>
                    {#if notice}
                        <p class="oc-page__state">{notice}</p>
                    {/if}
                    {#if shown.length}
                        <ul class="themes-grid warez-grid">
                            {#each shown as manifest (manifest.id)}
                                <ThemeCard
                                    {manifest}
                                    palette={palettes.get(manifest.id) ?? previewPalette(manifest)}
                                    selected={manifest.id === selectedId}
                                    active={manifest.id === pageTheme}
                                    starred={favoriteIds.includes(manifest.id)}
                                    onselect={() => select(manifest.id)}
                                    onapply={() => apply(manifest.id)}
                                    onstar={() => themeFavorites.toggle(manifest.id)}
                                />
                            {/each}
                        </ul>
                    {/if}
                </section>
            </div>

            <aside class="oc-page__detail themes-side" use:clearToasts aria-label={t(panel === 'guide' ? 'themes.page.guide.title' : 'themes.page.inspector.title')}>
                <div class="oc-page__detail-body">
                    <Button data-themes-back onclick={() => (sheetOpen = false)}>{t('themes.page.sheet.close')}</Button>
                    {#if panel === 'guide'}
                        <BuildYourOwn onrescan={() => void themes.refresh(true)} onlibrary={openLibrary} onsubmit={() => openPublishPage('themes')} />
                    {:else}
                        <ThemeDetail themeId={selected?.id ?? null} />
                    {/if}
                </div>
            </aside>
        </div>
    </Page>
{/if}

<style>
    .themes-grid {
        margin: 0;
        padding: 0;
        list-style: none;
    }

    :global(.themes-screen) {
        --themes-ctl-h: 32px;
    }

    :global(.themes-screen) :global(.oc-page__bar) {
        align-items: center;
        gap: var(--oc-space-2) var(--oc-space-3);
    }

    :global(.themes-screen) :global(.oc-page__bar .oc-field),
    :global(.themes-screen) :global(.oc-page__bar .oc-chip),
    :global(.themes-screen) :global(.oc-page__bar .oc-field) {
        width: 100%;
        padding-inline: 10px;
    }

    :global(.themes-screen) :global(.oc-page__bar .oc-field::placeholder) {
        color: var(--oc-text-secondary);
    }

    :global(.themes-screen) :global(.oc-page__bar .oc-label) {
        color: var(--oc-text-secondary);
        line-height: 1;
    }

    .themes-active {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-2);
        min-height: var(--themes-ctl-h);
        min-width: 0;
    }

    .themes-now {
        overflow: hidden;
        max-width: 260px;
        padding: 0;
        border: none;
        background: transparent;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-family: var(--font-mono);
        font-size: 12px;
        line-height: 1;
        color: var(--oc-green);
    }

    :global([data-themes-now]) {
        max-width: 260px;
        color: var(--oc-green);
        text-decoration: underline;
        text-underline-offset: 3px;
    }

    @media (max-width: 1023px) {
        :global(.themes-screen) {
            --themes-ctl-h: var(--oc-tap, 44px);
        }
    }

    .themes-body {
        display: flex;
    }

    .themes-body > :global(.oc-page__scroll) {
        flex: 1 1 0;
        min-width: 0;
    }

    .themes-side {
        flex: 0 0 380px;
    }

    :global([data-themes-back]) {
        display: none;
        width: 100%;
        margin-bottom: var(--oc-space-3);
    }

    @container oc-body (max-width: 719px) {
        .themes-side {
            display: none;
        }

        .themes-body--detail .themes-side {
            display: flex;
            flex: 1 1 100%;
            border-left: none;
        }

        .themes-body--detail :global(.oc-page__scroll) {
            display: none;
        }

        :global([data-themes-back]) {
            display: block;
        }
    }
</style>
