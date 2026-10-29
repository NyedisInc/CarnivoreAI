<script lang="ts">
  /* the home screen */
  import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { emptyMenu, emptyMenuNodes, type MenuSurface } from './empty-space-menu.svelte';

  let { surface = 'home' }: { surface?: MenuSurface } = $props();
  let marker = $state<HTMLElement | null>(null);

  function closeOnOutsidePress(event: PointerEvent): void {
    if (!emptyMenu.at) return;
    if (event.target instanceof Element && event.target.closest('.acm-menu') !== null) return;
    emptyMenu.at = null;
  }

  const MENU_LABEL: Readonly<Record<string, string>> = {
    side: 'opscenter.empty_menu.label_side',
    bottom: 'opscenter.empty_menu.label_bottom',
    area: 'opscenter.empty_menu.label_area',
  };
</script>

<svelte:window onpointerdowncapture={closeOnOutsidePress} />

{#if emptyMenu.at && emptyMenu.surface === surface}
  <span
    class="oc-empty-menu-anchor"
    style={`left: ${emptyMenu.at.x}px; top: ${emptyMenu.at.y}px`}
    bind:this={marker}
    aria-hidden="true"
  ></span>
  {#if marker}
    
    {#key `${emptyMenu.at.x},${emptyMenu.at.y}`}
    <CascadeMenu root={emptyMenuNodes()} anchor={marker} label={t(MENU_LABEL[emptyMenu.target] ?? 'opscenter.empty_menu.label')} onClose={() => (emptyMenu.at = null)} />
    {/key}
  {/if}
{/if}

<style>
  @layer components {
    .oc-empty-menu-anchor { position: fixed; width: 0; height: 0; pointer-events: none; }
  }
</style>
