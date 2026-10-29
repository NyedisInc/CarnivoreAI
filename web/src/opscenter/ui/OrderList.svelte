
<script lang="ts">
    import IconButton from '../../lib/base/IconButton.svelte';
    import Check from './Check.svelte';

    interface Item {
        id: string;
        label: string;
        on?: boolean;
        glyph?: string;
        earlier: string;
        later: string;
        /*  hidden  */
        movable?: boolean;
    }

    interface Props {
        items: readonly Item[];
        toggle?: boolean;
        toggleLabel?: (id: string) => string;
        ariaLabel?: string;
        onToggle?: (id: string, next: boolean) => void;
        onMove: (id: string, direction: 'up' | 'down') => void;
    }

    const { items, toggle = false, toggleLabel, ariaLabel, onToggle, onMove }: Props = $props();

    const movable = $derived(items.filter((i) => i.movable !== false).map((i) => i.id));
</script>

<div class="oc-order" role="list" aria-label={ariaLabel}>
    {#each items as item (item.id)}
        {@const can = item.movable !== false}
        {@const at = movable.indexOf(item.id)}
        <div class="oc-order__item" class:oc-order__item--off={!toggle && item.on === false} role="listitem" data-order-id={item.id}>
            <span class="oc-order__n" aria-hidden="true">{can ? at + 1 : ''}</span>
            {#if toggle}
                <span class="oc-order__name">
                    <Check
                        label={item.label}
                        checked={item.on ?? false}
                        glyph={item.glyph ?? ''}
                        ariaLabel={toggleLabel?.(item.id)}
                        onToggle={(next) => onToggle?.(item.id, next)}
                    />
                </span>
            {:else}
                <span class="oc-order__name">{item.label}</span>
            {/if}
            <IconButton label={item.earlier} icon="chevron-up" disabled={!can || at === 0} onclick={() => onMove(item.id, 'up')} />
            <IconButton label={item.later} icon="chevron-down" disabled={!can || at === movable.length - 1} onclick={() => onMove(item.id, 'down')} />
        </div>
    {/each}
</div>
