<script lang="ts">
  import { getContext } from 'svelte';
  import { t } from '../sdk';
  import type { HuddleItem } from './huddle-model';
  import { TAGGED_OPEN, type TaggedOpener } from './task-manager-tagged-open';

  let { item }: { item: HuddleItem } = $props();

  const open = getContext<TaggedOpener | undefined>(TAGGED_OPEN);
  const live = $derived(!!item.tagged_by);

  const label = $derived(item.tagged_by || t('cplug.huddle.tagged.not_running'));
</script>

{#if item.tagged_session_key && open && live}
  <button type="button" class="tkm-tagged tkm-tagged--open" data-btn="row" data-task-manager-tagged={item.id} data-task-manager-tagged-open={item.id}
          title={t('cplug.huddle.tagged.open')} aria-label={t('cplug.huddle.tagged.open_label', { name: label })}
          onclick={() => open(item.tagged_session_key as string)}>@{label}</button>
{:else if item.tagged_session_key}
  <p class="tkm-tagged" data-task-manager-tagged={item.id} title={t('cplug.huddle.tagged.tip')}>@{label}</p>
{/if}

<style>
  @layer components {
    .tkm-tagged {
      align-self: flex-start;
      min-width: 0;
      max-width: 100%;
      margin: 0;
      padding: 0 var(--oc-space-2);
      overflow: hidden;
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: var(--oc-space-5);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .tkm-tagged--open {
      --_btn-h: 0px;
      --_btn-fill-hover: transparent;
      background: none;
      cursor: pointer;
    }

    .tkm-tagged--open:hover {
      color: var(--oc-text-primary);
    }
  }
</style>
