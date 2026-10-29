<script lang="ts">
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import { placeAt } from '../drawer-tabs/place-at';
  import { t } from '../i18n/index.svelte';
  import { closeRailMenu, railMenu, railMenuItems } from './rail-menu.svelte';

  let { closed = false }: { closed?: boolean } = $props();
  let marker = $state<HTMLElement | null>(null);

</script>

{#if railMenu.at && railMenu.closed === closed}
  <span class="sbr-menu-anchor" bind:this={marker} use:placeAt={railMenu.at} aria-hidden="true"></span>
  {#if marker}
    
    {#key `${railMenu.at.x},${railMenu.at.y}`}
      <CascadeMenu root={railMenuItems()} anchor={marker} label={t('sidebar.rail.menu.label')} onClose={closeRailMenu} />
    {/key}
  {/if}
{/if}

<style>
  @layer components {
    .sbr-menu-anchor { position: fixed; width: 0; height: 0; pointer-events: none; }
  }
</style>
