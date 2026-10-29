<script lang="ts">
  /* nothing at all */
  import { t } from '../sdk';
  import TaskManagerMarker from './TaskManagerMarker.svelte';
  import { markerKey, markersInUse } from './task-manager-markers';
  import { dropUnusedMarkers, toggleViewMarker, viewFilter } from './task-manager-view-filter.svelte';
  import type { HuddleItem } from './huddle-model';

  let { items }: { items: HuddleItem[] } = $props();
  const inUse = $derived(markersInUse(items));

  $effect(() => dropUnusedMarkers(inUse.map((m) => m.id)));
</script>

{#if inUse.length > 0}
  <span class="hdm-set" role="group" aria-label={t('cplug.huddle.marker.label')} data-task-manager-marker-filter>
    {#each inUse as { id, count } (id)}
      {@const on = viewFilter.markers.includes(id)}
      {@const title = t(on ? 'cplug.huddle.marker.on_title' : 'cplug.huddle.marker.off_title', { name: t(markerKey(id)), count })}
      <button type="button" class="hdm-key" aria-pressed={on} aria-label={title} {title} data-task-manager-marker-key={id}
              onclick={() => toggleViewMarker(id, !on)}><TaskManagerMarker {id} size={10} /></button>
    {/each}
  </span>
{/if}

<style>
  @layer components {
    .hdm-set {
      display: inline-flex;
      flex: 0 1 auto;
      min-width: 0;
      height: 20px;
      border: 1px solid var(--oc-line-rule);
      border-radius: 2px;
    }

    .hdm-key {
      --_bd: transparent;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 0;
      padding: 0 5px;
      border: 1px solid var(--_bd);
      background: none;
      cursor: pointer;
      opacity: 0.55;
    }

    .hdm-key + .hdm-key {
      box-shadow: inset 1px 0 0 var(--oc-line-rule);
    }

    .hdm-key:hover,
    .hdm-key[aria-pressed='true'] {
      opacity: 1;
    }

    .hdm-key[aria-pressed='true'] {
      --_bd: var(--oc-orange);
    }
  }
</style>
