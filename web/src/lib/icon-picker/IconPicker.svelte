
<script lang="ts">
    import { t as catalogT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import IconMark from './IconMark.svelte';
    import {
        ICON_PICKER_KEYS as K,
        PICKER_COLUMNS,
        filterIcons,
        iconValue,
        moveIndex,
        resolveIcon,
        type PickableIcon,
    } from './icon-model';

    interface Props {
        value: string | null | undefined;
        onChange: (id: string | null) => void;
        onCancel?: () => void;
        t?: Translate;
        autofocus?: boolean;
    }

    let { value, onChange, onCancel, t = catalogT, autofocus = false }: Props = $props();

    const uid = $props.id();

    let query = $state('');
    let active = $state(0);
    let grid: HTMLDivElement | undefined = $state();
    let search: HTMLInputElement | undefined = $state();

    const shown = $derived(filterIcons(query, t));
    const cells = $derived<readonly (PickableIcon | null)[]>([null, ...shown]);
    const current = $derived.by(() => {
        const raw = iconValue(value);
        return raw === null ? null : (resolveIcon(raw)?.id ?? raw);
    });

    const cellId = (i: number): string => `${uid}-cell-${i}`;

    $effect(() => {
        const at = cells.findIndex((cell) => (cell ? cell.id : null) === current);
        active = at >= 0 && (at > 0 || query.trim() === '') ? at : (shown.length > 0 ? 1 : 0);
    });

    $effect(() => {
        if (autofocus) search?.focus();
    });

    function choose(i: number): void {
        const cell = cells[i];
        onChange(cell ? cell.id : null);
    }

    function onGridKey(event: KeyboardEvent): void {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            choose(active);
            return;
        }
        if (event.key === 'Escape' && onCancel) {
            event.preventDefault();
            onCancel();
            return;
        }
        const next = moveIndex(active, event.key, cells.length, PICKER_COLUMNS);
        if (next === null) return;
        event.preventDefault();
        active = next;
        document.getElementById(cellId(next))?.scrollIntoView?.({ block: 'nearest' });
    }

    function onSearchKey(event: KeyboardEvent): void {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            grid?.focus();
        } else if (event.key === 'Enter') {
            event.preventDefault();
            choose(active);
        } else if (event.key === 'Escape' && onCancel) {
            event.preventDefault();
            onCancel();
        }
    }
</script>

<div class="icp" role="group" aria-label={t(K.label)}>
    <label class="icp__search">
        <span class="icp__label">{t(K.searchLabel)}</span>
        <input
            bind:this={search}
            bind:value={query}
            class="icp__input"
            type="search"
            autocomplete="off"
            spellcheck="false"
            placeholder={t(K.searchPlaceholder)}
            onkeydown={onSearchKey}
        />
    </label>
    <div
        bind:this={grid}
        class="icp__grid"
        role="listbox"
        tabindex="0"
        aria-label={t(K.label)}
        aria-activedescendant={cellId(active)}
        onkeydown={onGridKey}
    >
        {#each cells as cell, i (cell ? cell.id : '')}
            {@const selected = (cell ? cell.id : null) === current}
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <div
                id={cellId(i)}
                class="icp__cell"
                class:icp__cell--none={!cell}
                class:icp__cell--active={i === active}
                role="option"
                tabindex="-1"
                aria-selected={selected}
                title={cell ? t(cell.label) : t(K.none)}
                onclick={() => { active = i; choose(i); }}
            >
                {#if cell}
                    <IconMark id={cell.id} size={16} />
                    <span class="icp__sr">{t(cell.label)}</span>
                {:else}
                    <span class="icp__none" aria-hidden="true"></span>
                    <span class="icp__sr">{t(K.none)}</span>
                {/if}
            </div>
        {/each}
    </div>
    {#if shown.length === 0}
        <p class="icp__empty">{t(K.empty)}</p>
    {/if}
</div>
