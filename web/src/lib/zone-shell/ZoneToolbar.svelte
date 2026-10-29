<script lang="ts">
  import type { Zone } from './zone.svelte';

  let { zone }: { zone: Zone } = $props();

  const toolbar = $derived(zone.toolbar);
</script>

{#if toolbar && zone.spec.toolbar !== 'none'}
  <div class="zone-toolbar" data-oc-base data-zone-toolbar={toolbar.hostId} data-toolbar-place={zone.spec.toolbar}>
    {#if toolbar.action}{@render toolbar.action()}{/if}
    {#each toolbar.groups as group, i (i)}{@render group()}{/each}
    {#if toolbar.tools}{@render toolbar.tools()}{/if}
  </div>
{/if}

<style>
  @layer components {
    .zone-toolbar {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .zone-toolbar[data-toolbar-place='strip'] {
      display: contents;
    }
  }
</style>
