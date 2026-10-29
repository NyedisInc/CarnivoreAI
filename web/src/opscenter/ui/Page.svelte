
<script lang="ts">
    import type { Snippet } from 'svelte';
    import { isInset } from './page-inset';
    import { viewport } from '../engine/viewport.svelte';
    import { watchScrollAway } from './scroll-away';
    import { t } from '../../lib/i18n/index.svelte';
    import Icon from './Icon.svelte';
    import { closeMenuPageGuarded, openMenuPages } from '../../lib/menu-page/menu-page-shell.svelte';

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
    let omni = $state<HTMLElement | undefined>();
    let rowsEl = $state<HTMLElement | undefined>();
    let away = $state(false);
    $effect(() => {
        if (!viewport.narrow || inset || embedded || !root || !rowsEl) return;
        return watchScrollAway(root, rowsEl, (value) => (away = value));
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

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
    bind:this={root}
    class="oc-page {extra}"
    class:oc-page--embedded={embedded || inset}
    class:oc-page--inset={inset}
    class:oc-page--away={away}
    data-oc-base
    role="region"
    aria-label={ariaLabel ?? title}
    {onkeydown}
    {...rest}
>
    {#if !inset && !bare}
        <header class="oc-titlebar" class:oc-titlebar--search={!!search} class:oc-titlebar--back={showBack}>
            {#if showBack}
                <button type="button" class="oc-titlebar__back" data-page-back aria-label={t('opscenter.components.back')} onclick={goBack}>
                    <Icon name={backIcon} size={backIcon === 'arrow-left' ? 20 : 14} strokeWidth={backIcon === 'arrow-left' ? 1.75 : 1.3} />
                </button>
            {/if}
            {#if search}
                <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
                <div class="oc-titlebar__omni oc-focus-host" bind:this={omni} onclick={focusOmni}>
                    <h1 class="oc-titlebar__title" tabindex="-1" bind:this={titleEl}>{title}</h1>
                    <div class="oc-titlebar__omni-row">
                        <Icon name="search" size={12} strokeWidth={2} />
                        {@render search()}
                    </div>
                </div>
            {:else}
                <h1 class="oc-titlebar__title" tabindex="-1" bind:this={titleEl}>{#if icon}<span class="oc-titlebar__icon"><Icon name={icon} size={14} /></span>{/if}{title}</h1>
                <span class="oc-titlebar__sub">{@render subContent()}</span>
            {/if}
            {#if controls}<div class="oc-titlebar__controls">{@render controls()}</div>{/if}
            {#if hasActions}<div class="oc-titlebar__actions">{@render actionsContent()}</div>{/if}
        </header>
    {/if}

    {#if tabs || bar || (inset && (hasSub || hasActions))}
        <div class="oc-page__away" bind:this={rowsEl}>
        {#if tabs}
            <div class="oc-page__tabs">{@render tabs()}</div>
        {/if}

        {#if bar || (inset && (hasSub || hasActions))}
            <div class="oc-page__bar">
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

    {#if notes}
        <div class="oc-page__notes">{@render notes()}</div>
    {/if}

    {@render children?.()}

    {#if foot}
        <div class="oc-page__foot">{@render foot()}</div>
    {/if}
</div>
