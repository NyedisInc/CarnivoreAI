
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Translate } from '../sessions/types';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import ManagerToggle from './ManagerToggle.svelte';
    import ManagerImage from './ManagerImage.svelte';
    import WarezCard from '../catalog/WarezCard.svelte';
    import type { ManagerItem, ManagerToggleState } from './types';

    interface Props {
        item: ManagerItem;
        /* the detail pane */
        selected: boolean;
        switchable: boolean;
        toggle?: ManagerToggleState;
        t: Translate;
        /* the detail pane */
        onOpen?: (id: string) => void;
        onToggle?: (id: string, next: boolean) => void;
        extra?: Snippet<[ManagerItem]>;
        rowSelect?: boolean;
        media?: boolean;
        mediaBody?: Snippet<[ManagerItem]>;
        onStar?: (id: string) => void;
        warez?: boolean;
        warezKind?: string;
        act?: Snippet<[ManagerItem]>;
    }

    const { item, selected, switchable, toggle, t, onOpen, onToggle, extra, rowSelect = false, media = false, mediaBody, onStar, warez = false, warezKind = '', act }: Props = $props();

    const rich = $derived(
        !rowSelect && (media || Boolean(item.icon || item.iconSvg || item.iconFamilies?.length || item.tags?.length || item.byline || item.status || item.metric)),
    );
    const showMedia = $derived(media && !rowSelect);
    const overlaid = $derived(showMedia && item.corner !== undefined);
    const statusShown = $derived(Boolean(item.status) && (item.status?.tone === 'warn' || !(switchable && onToggle && typeof item.enabled === 'boolean')));
    const tileMarks = $derived((item.iconFamilies ?? []).slice(0, 3).map((family) => providerMark(family, 14)));
    const marks = $derived(rowSelect ? [...(item.marks ?? []), ...(item.tags ?? [])] : (item.marks ?? []));

    const warezFlagChips = $derived((item.chips ?? []).filter((chip) => WAREZ_FLAG_CHIPS.includes(chip.id)));

    function onRowClick(event: MouseEvent): void {
        if (!onOpen) return;
        const target = event.target as Element | null;
        if (target?.closest('button, a, input, select, textarea, summary, label, [role="switch"], [role="menu"]')) return;
        onOpen(item.id);
    }

    const WAREZ_FLAG_CHIPS = ['shadowed', 'drifted', 'missing', 'flagged', 'unused'];
</script>

{#snippet toggleSwitch()}
    {#if switchable && onToggle && typeof item.enabled === 'boolean'}
        <ManagerToggle
            name={item.name}
            enabled={item.enabled}
            busy={toggle?.busy ?? false}
            {t}
            onToggle={(next) => onToggle(item.id, next)}
        />
    {/if}
{/snippet}

{#snippet mediaBox()}
    <div class="oc-card-media mgr-card__media" aria-hidden="true" data-card-media>
        {#if mediaBody}{@render mediaBody(item)}{:else if item.icon}<Icon name={item.icon} size={40} />{:else}{Array.from(item.name || '?')[0]}{/if}
        {#if item.imagePath}<ManagerImage path={item.imagePath} />{/if}
    </div>
{/snippet}

{#snippet warezThumb()}
    {#if mediaBody}{@render mediaBody(item)}{:else if item.icon}<Icon name={item.icon} size={32} />{:else}<span class="catalog-card__letter" aria-hidden="true">{Array.from(item.name || '?')[0]?.toUpperCase()}</span>{/if}
    {#if item.imagePath}<ManagerImage path={item.imagePath} />{/if}
{/snippet}

{#snippet warezAct()}
    {#if statusShown && item.status}<span class="mgr-card__status mgr-card__status--{item.status.tone}">{item.status.label}</span>{/if}
    {@render toggleSwitch()}
    {@render act?.(item)}
{/snippet}

{#snippet warezFlags()}
    {#each warezFlagChips as chip (chip.id)}
        <span class="mgr-chip" role="img" aria-label={chip.label} title={chip.label}>{#if chip.icon}<Icon name={chip.icon} size={14} strokeWidth={1.5} />{/if}</span>
    {/each}
{/snippet}

{#snippet warezStar()}
    {#if onStar}
        <button
            type="button"
            class="mgr-card__star"
            data-act="card-star"
            aria-pressed={item.starred === true}
            aria-label={t('skills.card.star', { name: item.name })}
            onclick={() => onStar(item.id)}
        ><Icon name="star" size={16} strokeWidth={1.4} fill={item.starred ? 'solid' : 'outline'} /></button>
    {/if}
{/snippet}

{#if warez && !rowSelect}
    <WarezCard kind={warezKind} itemId={item.id} {t} name={item.name} brief={item.brief ?? null} onOpen={onOpen ? () => onOpen(item.id) : null} {selected} thumb={warezThumb} act={warezAct} beside={warezStar} flags={warezFlagChips.length > 0 ? warezFlags : undefined}>
        {#if extra}{@render extra(item)}{/if}
        {#if toggle?.error}<p class="mgr-card__error" role="alert">{toggle.error}</p>{/if}
    </WarezCard>
{:else}

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<article
    class="mgr-card pl-panel"
    class:mgr-card--rich={rich}
    class:mgr-card--selected={selected}
    class:mgr-card--openable={!!onOpen}
    data-item-id={item.id}
    onclick={onRowClick}
>
    {#if showMedia}
        {#if overlaid}
            <div class="mgr-card__stage">
                {@render mediaBox()}
                <div class="mgr-card__over mgr-card__over--title" data-card-title>
                    {#if item.iconSvg}<span class="mgr-card__over-mark" aria-hidden="true">{@html item.iconSvg}</span>{/if}
                    {#if onOpen}
                        <button type="button" class="mgr-card__name mgr-card__open" aria-expanded={selected} onclick={() => onOpen(item.id)}>{item.name}</button>
                    {:else}
                        <span class="mgr-card__name">{item.name}</span>
                    {/if}
                    {#if onStar}
                        <button
                            type="button"
                            class="mgr-card__star"
                            data-act="card-star"
                            aria-pressed={item.starred === true}
                            aria-label={t('skills.card.star', { name: item.name })}
                            onclick={() => onStar(item.id)}
                        ><Icon name="star" size={16} strokeWidth={1.4} fill={item.starred ? 'solid' : 'outline'} /></button>
                    {/if}
                </div>
                {#if item.corner && item.corner.length > 0}
                    <div class="mgr-card__over mgr-card__over--corner" data-card-corner>
                        {#each item.corner as line, i (i)}<span>{line}</span>{/each}
                    </div>
                {/if}
            </div>
        {:else}
            {@render mediaBox()}
        {/if}
    {/if}
    {#if !overlaid}
    <div class="mgr-card__head">
        {#if rich && item.iconSvg}<span class="oc-icon-tile">{@html item.iconSvg}</span>
        {:else if rich && !showMedia && item.icon}<span class="oc-icon-tile"><Icon name={item.icon} size={16} /></span>
        {:else if rich && !showMedia && tileMarks.length > 0}
            <span class="oc-icon-tile oc-icon-tile--marks">
                {#each tileMarks as mark, i (i)}<span role="img" aria-label={mark.label} title={mark.label}>{@html mark.svg}</span>{/each}
            </span>
        {/if}
        {#if onOpen}
            <button
                type="button"
                class="mgr-card__name mgr-card__open"
                aria-expanded={selected}
                onclick={() => onOpen(item.id)}>{item.name}</button
            >
        {:else}
            <span class="mgr-card__name">{item.name}</span>
        {/if}
        {#if rich && item.status}
            <span class="mgr-card__slot">
                <span class="mgr-card__status mgr-card__status--{item.status.tone}">{item.status.label}</span>
                {@render toggleSwitch()}
            </span>
        {:else}
            {@render toggleSwitch()}
        {/if}
    </div>
    {/if}
    {#if item.meta && !(rich && item.meta === item.byline)}<p class="mgr-card__meta">{item.meta}</p>{/if}
    {#if item.brief}<p class="mgr-card__brief">{item.brief}</p>{/if}
    {#if !rich && marks.length > 0}
        <ul class="mgr-card__marks">
            {#each marks as mark (mark)}<li class="mgr-mark">{mark}</li>{/each}
        </ul>
    {/if}
    {#if extra}{@render extra(item)}{/if}
    {#if toggle?.error}<p class="mgr-card__error" role="alert">{toggle.error}</p>{/if}
    {#if rich}
        <div class="mgr-card__foot">
            {#if overlaid}
                {#if item.chips && item.chips.length > 0}
                    <ul class="mgr-card__chips">
                        {#each item.chips as chip (chip.id)}
                            <li class="mgr-chip" role="img" aria-label={chip.label} title={chip.label}>
                                {#if chip.svg}{@html chip.svg}{:else if chip.icon}<Icon name={chip.icon} size={14} strokeWidth={1.5} />{/if}
                            </li>
                        {/each}
                    </ul>
                {/if}
            {:else if (item.marks && item.marks.length > 0) || (item.tags && item.tags.length > 0)}
                <ul class="mgr-card__marks">
                    {#each [...(item.marks ?? []), ...(item.tags ?? [])] as mark (mark)}<li class="mgr-mark">{mark}</li>{/each}
                </ul>
            {/if}
            {#if item.byline}<span class="mgr-card__byline">{item.byline}</span>{/if}
            {#if item.metric}<span class="mgr-card__metric">{item.metric}</span>{/if}
            {#if overlaid}
                {#if statusShown && item.status}<span class="mgr-card__status mgr-card__status--{item.status.tone}">{item.status.label}</span>{/if}
                {@render toggleSwitch()}
            {/if}
        </div>
    {/if}
</article>
{/if}
