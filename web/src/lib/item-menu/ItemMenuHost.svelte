
<script lang="ts">
    import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
    import { placeAt } from '../drawer-tabs/place-at';
    import { closeItemMenu, itemMenuState } from './open.svelte';
    import { ROW_MENU_PANEL_ID, ROW_MENU_TYPES as ROW_TYPES } from './row-context';

    let marker = $state<HTMLElement | null>(null);
</script>


{#each itemMenuState.open ? [itemMenuState.open] : [] as open (open.seq)}
    
    {#if open.at}<span class="hm-anchor" bind:this={marker} use:placeAt={open.at} aria-hidden="true" tabindex="-1"
        onfocus={() => (open.anchor as HTMLElement).focus?.({ preventScroll: true })}></span>{/if}
    {#if !open.at || marker}
        <CascadeMenu root={open.nodes} anchor={open.at ? marker : (open.anchor as HTMLElement)} label={open.ariaLabel} nestedIn={open.nestedIn}
            panelId={ROW_TYPES.has(open.type) ? ROW_MENU_PANEL_ID : undefined} onClose={closeItemMenu} />
    {/if}
{/each}

<style>
    @layer components {
        .hm-anchor { position: fixed; width: 0; height: 0; pointer-events: none; }
    }
</style>
