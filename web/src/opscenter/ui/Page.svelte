
<script lang="ts" module>
    let sideSeq = 0;
    const FIND_INPUT = ['.oc-titlebar__find', '.oc-titlebar__omni'].map((home) => `${home} input`).join(',');
    const PICK_TARGETS = ['a', 'button', '[role="menuitem"]', '[role="option"]', '[role="tab"]', '[role="treeitem"]'].join(',');
</script>

<script lang="ts">
    import { tick, type Snippet } from 'svelte';
    import type { PageFrame } from './page-frame';
    import { isInset } from './page-inset';
    import { viewport } from '../engine/viewport.svelte';
    import { watchScrollAway } from './scroll-away';
    import { watchFrameStickyTop } from '../../../../client/js/frame-sticky-top.js';
    import { t } from '../../lib/i18n/index.svelte';
    import Icon from './Icon.svelte';
    import Button from '../../lib/base/Button.svelte';
    import IconButton from '../../lib/base/IconButton.svelte';
    import { raiseFlag } from '../../lib/page-flags/page-flags';
    import { closeMenuPageFromX, closeMenuPageGuarded, menuPageState, openMenuPages } from '../../lib/menu-page/menu-page-shell.svelte';
    import { MENU_PAGES } from '../../lib/menu-page/menu-pages';
    import { drawerResize } from '../../lib/menu-page/menu-page-resize';
    import Self from './Page.svelte';

    interface Props {
        title: string;
        icon?: string;
        label?: string;
        count?: string;
        onClose?: () => void;
        closeLabel?: string;
        embedded?: boolean;
        bare?: boolean;
        ariaLabel?: string;
        class?: string;
        root?: HTMLDivElement | undefined;
        titleEl?: HTMLHeadingElement | undefined;
        onkeydown?: (event: KeyboardEvent) => void;
        onDrawerClose?: () => void;
        sub?: Snippet;
        actions?: Snippet;
        search?: Snippet;
        backIcon?: 'arrow-left' | 'chevron-left';
        controls?: Snippet;
        tabs?: Snippet;
        bar?: Snippet;
        notes?: Snippet;
        foot?: Snippet;
        children?: Snippet;
        frame: PageFrame;
        scroll?: 'frame' | 'self';
        stack?: boolean;
        side?: Snippet;
        sideLabel?: string;
        detail?: Snippet;
        detailTitle?: string;
        detailActions?: Snippet;
        onDetailClose?: () => void;
        find?: Snippet;
        pair?: boolean;
        pairOpen?: boolean;
        pairTitle?: string;
        onPairClose?: () => void;
        pairPart?: 'list' | 'page';
        style?: string;
        [attribute: `data-${string}`]: string | undefined;
    }

    let {
        title,
        icon,
        label,
        count,
        onClose,
        closeLabel = 'close',
        embedded = false,
        bare = false,
        ariaLabel,
        class: extra = '',
        root = $bindable(),
        titleEl = $bindable(),
        onkeydown,
        onDrawerClose,
        sub,
        actions,
        search,
        backIcon = 'arrow-left',
        controls,
        tabs,
        bar,
        notes,
        foot,
        children,
        frame,
        scroll,
        stack = false,
        side,
        sideLabel,
        detail,
        detailTitle,
        detailActions,
        onDetailClose,
        find,
        pair = false,
        pairOpen = false,
        pairTitle,
        onPairClose,
        pairPart,
        ...rest
    }: Props = $props();

    const inset = isInset();
    const hasSub = $derived(!!sub || !!label || !!count);
    const hasActions = $derived(!!actions);
    const showBack = $derived(!!onClose && !inset && !embedded && viewport.narrow);
    function goBack(): void {
        if (openMenuPages().length) void closeMenuPageGuarded();
        else onClose?.();
    }
    const selfScroll = $derived(frame === 'canvas' || scroll === 'self');
    const findUsable = $derived(!!find && !inset);
    const headerFind = $derived(findUsable && !viewport.narrow);
    const omniSearch = $derived(search ?? (viewport.narrow && findUsable ? find : undefined));
    $effect(() => {
        if (import.meta.env.DEV && find && inset) console.warn('page-find-on-inset', title);
    });
    // the page frame
    let findHadFocus = false;
    $effect.pre(() => {
        void viewport.narrow;
        findHadFocus = !!root?.querySelector('.oc-titlebar__find, .oc-titlebar__omni')?.contains(document.activeElement);
    });
    $effect(() => {
        void viewport.narrow;
        if (!findHadFocus) return;
        findHadFocus = false;
        void tick().then(() => root?.querySelector<HTMLInputElement>(FIND_INPUT)?.focus());
    });
    const showPicker = $derived(frame === 'nav' && !!side && !pair);
    let sideOpen = $state(false);
    const sideId = `oc-page-side-${++sideSeq}`;
    let pickerEl = $state<HTMLElement | null>(null);
    let sideEl = $state<HTMLElement | null>(null);
    let scrollBeforeSheet: number | null = null;
    function closeSide(restore = true): void {
        if (!sideOpen) return;
        sideOpen = false;
        if (restore && root && scrollBeforeSheet !== null) root.scrollTop = scrollBeforeSheet;
        scrollBeforeSheet = null;
        if (restore) void tick().then(() => pickerEl?.focus());
    }
    function toggleSide(): void {
        if (sideOpen) {
            closeSide();
            return;
        }
        sideOpen = true;
        if (!root || root.scrollTop <= 0) return;
        scrollBeforeSheet = root.scrollTop;
        void tick().then(() => sideEl?.scrollIntoView?.({ block: 'start' }));
    }
    function frameKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Escape' || !sideOpen) return;
        event.stopPropagation();
        closeSide();
    }
    function escapeOnFrame(node: HTMLElement): () => void {
        node.addEventListener('keydown', frameKeydown);
        return () => node.removeEventListener('keydown', frameKeydown);
    }
    function sidePicked(event: MouseEvent): void {
        if ((event.target as HTMLElement).closest(PICK_TARGETS)) closeSide(false);
    }
    const isMenuPage = $derived(!!root && MENU_PAGES.some((p) => p.containerId === root?.parentElement?.id));
    const drawer = $derived(!inset && !embedded && !bare && !viewport.narrow && menuPageState.surface && isMenuPage);
    const pairDrawers = $derived(pair && !pairPart && frame === 'nav' && !inset && !embedded && !bare && !viewport.narrow && menuPageState.surface);
    let pairListW = $state(0);
    $effect(() => {
        const el = root;
        if (!pairDrawers || !el || typeof ResizeObserver !== 'function') return;
        const ro = new ResizeObserver(() => (pairListW = el.getBoundingClientRect().width || pairListW));
        ro.observe(el);
        return () => ro.disconnect();
    });
    let omni = $state<HTMLElement | undefined>();
    let rowsEl = $state<HTMLElement | undefined>();
    let away = $state(false);
    $effect(() => {
        if (!viewport.narrow || inset || embedded || !root || !rowsEl) return;
        return watchScrollAway(root, rowsEl, (value) => (away = value));
    });
    $effect(() => {
        if (!viewport.narrow || inset || !root) return;
        void rowsEl;
        return watchFrameStickyTop(root);
    });

    function focusOmni(event: MouseEvent): void {
        if ((event.target as HTMLElement).closest('input')) return;
        omni?.querySelector<HTMLInputElement>('input')?.focus();
    }
</script>

{#snippet subContent()}
    {#if sub}
        {@render sub()}
    {:else}
        {#if label}<span class="oc-label">{label}</span>{/if}
        {#if count}<span class="oc-titlebar__count">{count}</span>{/if}
    {/if}
{/snippet}

{#snippet actionsContent()}
    {#if actions}{@render actions()}{/if}
{/snippet}

{#if pairDrawers}
    <Self {title} {icon} {label} {count} {onClose} {closeLabel} {ariaLabel} class={extra} {onkeydown} {sub} {actions} {controls} {find} {search} {backIcon}
        frame="nav" {scroll} {side} {sideLabel} pair pairPart="list" bind:root bind:titleEl {...rest} />
    {#if pairOpen}
        <Self title={pairTitle ?? title} class={extra} {onkeydown} onDrawerClose={onPairClose} {tabs} {bar} {notes} {foot} {children}
            frame="nav" {scroll} {stack} {detail} {detailTitle} {detailActions} {onDetailClose} pair pairPart="page"
            {...rest} style={`--oc-drawer-offset: ${pairListW}px`} />
    {/if}
{:else}
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
    bind:this={root}
    class="oc-page {extra}"
    class:oc-page--drawer-list={pairPart === 'list'}
    class:oc-page--drawer-stacked={pairPart === 'page'}
    {...rest}
    data-pair={pair ? (pairPart ?? 'one') : undefined}
    class:oc-page--embedded={embedded || inset}
    class:oc-page--inset={inset}
    class:oc-page--away={away}
    data-oc-base
    data-frame={frame}
    role="region"
    aria-label={ariaLabel ?? title}
    {onkeydown}
>
    {#if !inset && !bare}
        <header class="oc-titlebar" class:oc-titlebar--search={!!omniSearch} class:oc-titlebar--find={headerFind} class:oc-titlebar--back={showBack} class:oc-titlebar--drawer={drawer} data-frame-region="header" data-btn-density="frame">
            {#if drawer}
                <IconButton label={t('sidebar.flyout.close', { name: title })} variant="close" icon="close" iconSize={14}
                    data-drawer-close onclick={() => (onDrawerClose ? onDrawerClose() : void closeMenuPageFromX())} />
            {/if}
            {#if showBack}
                <button type="button" class="oc-titlebar__back" data-btn="row" data-size="auto" data-overflow="visible" data-page-back aria-label={t('opscenter.components.back')} onclick={goBack} {@attach () => raiseFlag('page-back')}>
                    <Icon name={backIcon} size={backIcon === 'arrow-left' ? 20 : 14} strokeWidth={backIcon === 'arrow-left' ? 1.75 : 1.3} />
                </button>
            {/if}
            {#if omniSearch}
                <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <div class="oc-titlebar__omni oc-focus-host" bind:this={omni} onclick={focusOmni}>
                    <h1 class="oc-titlebar__title" tabindex="-1" bind:this={titleEl}>{title}</h1>
                    <div class="oc-titlebar__omni-row" role="search">
                        <Icon name="search" size={12} strokeWidth={2} />
                        {@render omniSearch()}
                    </div>
                </div>
            {:else}
                <h1 class="oc-titlebar__title" tabindex="-1" bind:this={titleEl}>{#if icon}<span class="oc-titlebar__icon"><Icon name={icon} size={14} /></span>{/if}{title}</h1>
                <span class="oc-titlebar__sub">{@render subContent()}</span>
            {/if}
            {#if headerFind && find}<div class="oc-titlebar__find" role="search" data-frame-region="find">{@render find()}</div>{/if}
            {#if controls}<div class="oc-titlebar__controls">{@render controls()}</div>{/if}
            {#if hasActions}<div class="oc-titlebar__actions">{@render actionsContent()}</div>{/if}
        </header>
    {/if}

    {#if frame === 'nav'}
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        
        <div class="oc-page__frame" class:oc-page__frame--detail={!!detail} data-frame-region="frame" data-scroll={selfScroll ? 'self' : 'frame'} data-pair={pair ? '' : undefined} {@attach escapeOnFrame}>
            {#if side}
                <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
                <aside id={sideId} class="oc-page__side" data-frame-region="side" data-open={sideOpen ? '' : undefined} aria-label={ariaLabel ?? title} onclick={sidePicked} bind:this={sideEl}>
                    <div class="oc-page__sheet-head"><IconButton label={t('opscenter.page.side_close')} icon="close" variant="close" onclick={() => closeSide()} /></div>
                    {@render side()}
                </aside>
            {/if}
            {#if pairPart !== 'list'}
                <div class="oc-page__col">
                    {@render rows()}
                    {@render notesRow()}
                    {@render body()}
                </div>
                {@render detailRegion()}
            {/if}
        </div>
    {:else}
        {@render rows()}
        {@render notesRow()}
        {@render body()}
    {/if}

    {#if foot}
        <div class="oc-page__foot" data-frame-region="foot">{@render foot()}</div>
    {/if}
    {#if drawer && pairPart !== 'list'}
        
        <div class="oc-page__resize" role="separator" aria-orientation="vertical" tabindex="0" aria-label={t('drawer.resize.label')}
            aria-valuemin={0} {@attach drawerResize(() => root)}></div>
    {/if}
</div>
{/if}


{#snippet rows()}
    {#if tabs || bar || showPicker || (inset && (hasSub || hasActions))}
        <div class="oc-page__away" bind:this={rowsEl}>
        {#if tabs}
            <div class="oc-page__tabs" data-frame-region="tabs" data-btn-density="frame">{@render tabs()}</div>
        {/if}

        {#if bar || showPicker || (inset && (hasSub || hasActions))}
            <div class="oc-page__bar" class:oc-page__bar--picker={showPicker && !bar} data-frame-region="tools" data-btn-density="frame">
                {#if showPicker}
                    <span class="oc-page__picker">
                        <Button bind:element={pickerEl} variant="secondary" aria-controls={sideId} aria-expanded={sideOpen} onclick={toggleSide}>{sideLabel ?? title}</Button>
                    </span>
                {/if}
                {#if bar}{@render bar()}{/if}
                {#if inset && (hasSub || hasActions)}
                    <div class="oc-page__inset-end">
                        {#if hasSub}<span class="oc-titlebar__sub">{@render subContent()}</span>{/if}
                        {#if hasActions}<div class="oc-titlebar__actions">{@render actionsContent()}</div>{/if}
                    </div>
                {/if}
            </div>
        {/if}
        </div>
    {/if}
{/snippet}

{#snippet notesRow()}
    {#if notes}
        <div class="oc-page__notes" data-frame-region="notes">{@render notes()}</div>
    {/if}
{/snippet}


{#snippet body()}
        <div class="oc-page__body" class:oc-page__body--detail={frame === 'column' && !!detail} data-scroll={selfScroll ? 'self' : 'frame'} data-frame-region="body">
            {#if selfScroll}
                <div class="oc-page__fill">{@render children?.()}</div>
            {:else}
                <div class="oc-page__scroll"><div class="oc-page__main" class:oc-page__main--stack={stack}>{@render children?.()}</div></div>
            {/if}
            {#if frame === 'column'}{@render detailRegion()}{/if}
        </div>
{/snippet}


{#snippet detailRegion()}
    {#if detail}
        <aside class="oc-page__detail oc-page__detail--frame" data-frame-region="detail" aria-label={detailTitle ?? title}>
            <div class="oc-page__detail-head" data-btn-density="frame">
                <h2 class="oc-page__detail-title">{detailTitle ?? ''}</h2>
                {#if detailActions}<div class="oc-page__detail-actions">{@render detailActions()}</div>{/if}
                {#if onDetailClose}<IconButton label={t('opscenter.page.detail_close')} icon="close" variant="close" onclick={onDetailClose} />{/if}
            </div>
            <div class="oc-page__detail-body">{@render detail()}</div>
        </aside>
    {/if}
{/snippet}
