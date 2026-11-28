<script lang="ts">
  import { untrack, type Snippet } from 'svelte';
  import ZonePane from './ZonePane.svelte';
  import ZoneTabContext from './ZoneTabContext.svelte';
  import type { Zone } from './zone.svelte';
  import type { TabRef } from './zone-types';

  let { zone, tab, mount = 'all', group = false, fold = false, only = undefined, bare = false }: { zone: Zone; tab: Snippet<[TabRef]>; mount?: 'all' | 'active' | 'visited'; group?: boolean; fold?: boolean; only?: (tab: TabRef) => boolean; bare?: boolean } = $props();

  let visited = $state<Record<string, true>>({});
  $effect(() => {
    if (mount !== 'visited') return;
    const key = zone.active?.key;
    if (key && !untrack(() => visited[key])) {
      visited[key] = true;
    }
  });

  const drawn = $derived(
    (mount === 'all'
      ? zone.tabs
      : mount === 'visited'
        ? zone.tabs.filter((one) => one.key === zone.active?.key || Boolean(visited[one.key]))
        : zone.tabs.filter((one) => one.key === zone.active?.key)
    ).filter((one) => !only || only(one)),
  );
</script>

{#each drawn as one (one.key)}
  {#if bare}
    <ZoneTabContext {zone} tab={one} pane={false}>{@render tab(one)}</ZoneTabContext>
  {:else}
    <ZonePane {zone} tab={one} body={tab} {group} {fold} />
  {/if}
{/each}
