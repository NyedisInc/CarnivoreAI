<script lang="ts">
  import { untrack, type Snippet } from 'svelte';
  import ZoneTabContext from './ZoneTabContext.svelte';
  import type { Zone } from './zone.svelte';
  import type { TabRef } from './zone-types';

  let { zone, tab, body, group = false, fold = false }: { zone: Zone; tab: TabRef; body: Snippet<[TabRef]>; group?: boolean; fold?: boolean } = $props();

  const key = untrack(() => tab.key);

  const active = $derived(zone.spec.active() === key);

  const watch = untrack(() => zone.watch(key));
</script>

<ZoneTabContext {zone} {tab}>
<div class="zone-pane" class:zone-pane--hidden={!active && !fold} class:zone-pane--gone={!active && fold} class:zone-pane--stacked={group} class:oc-tabpane-hidden={group && !active}
  data-oc-base data-zone-pane={key} data-zone-visible={zone.visibility(key)} data-tab-pane={group ? key : undefined} data-theme-scope={group ? '' : undefined}
  inert={!active} aria-hidden={active ? undefined : 'true'} {@attach watch}>
  {@render body(tab)}
</div>
</ZoneTabContext>

<style>
  @layer components {
    .zone-pane {
      display: flex;
      flex: 1 1 auto;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
    }

    .zone-pane--stacked {
      position: absolute;
      inset: 0;
      flex: none;
    }

    .zone-pane--hidden {
      visibility: hidden;
    }

    .zone-pane--gone {
      display: none;
    }
  }
</style>
