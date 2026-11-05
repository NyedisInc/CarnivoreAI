<script lang="ts">
  import { t } from '../sdk';
  import { buttonAttrs } from '../sdk/ui';
  import { findItem } from './huddle.svelte';
  import { jumpToParent } from './task-manager-fork.svelte';
  import type { HuddleItem } from './huddle-model';

  let { item }: { item: HuddleItem } = $props();

  const parent = $derived(item.forked_from ?? null);
  const label = $derived(t('cplug.huddle.fork.from', { title: item.forked_from_title ?? '' }));
  const here = $derived(parent !== null && findItem(parent) !== null);
</script>

{#if parent !== null}
  <p class="tkm-fork" data-task-manager-forked={item.id}>
    {#if here}
      <button type="button" class="tkm-fork-link" {...buttonAttrs('quiet', 'bare')} data-task-manager-forked-open={item.id} onclick={() => jumpToParent(parent)}>{label}</button>
    {:else}
      <span class="tkm-fork-plain">{label}</span>
    {/if}
  </p>
{/if}

<style>
  @layer components {
    .tkm-fork {
      min-width: 0;
      margin: 0;
      padding: var(--oc-border);
      overflow: hidden;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .tkm-fork-link {
      --_bd: currentColor;
      display: inline-block;
      max-width: 100%;
      margin: -1px;
      overflow: hidden;
      padding: 0;
      background: none;
      border: 1px solid transparent;
      color: inherit;
      font: inherit;
      letter-spacing: inherit;
      text-overflow: ellipsis;
      text-transform: inherit;
      white-space: nowrap;
      cursor: pointer;
    }

    .tkm-fork-link:hover,
    .tkm-fork-link:focus-visible {
      color: var(--oc-text-bright);
      text-decoration: underline;
    }
  }
</style>
