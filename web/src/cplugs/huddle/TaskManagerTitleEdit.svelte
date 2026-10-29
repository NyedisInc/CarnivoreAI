<script lang="ts">
  /* Escape cancels */
  import { t } from '../sdk';
  import { baseField } from './task-manager-base-field';
  import { saveTitle } from './huddle.svelte';
  import { MAX_TITLE } from './huddle-density';
  import type { HuddleItem } from './huddle-model';
  import { editRequest, takeEdit } from './task-manager-edit-request.svelte';

  let { item }: { item: HuddleItem } = $props();

  let editing = $state(false);
  let draft = $state('');

  function start(): void {
    draft = item.title ?? '';
    editing = true;
  }

  $effect(() => {
    if (editRequest.title === item.id && takeEdit('title', item.id)) start();
  });

  async function commit(): Promise<void> {
    if (await saveTitle(item, draft)) editing = false;
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      void commit();
    } else if (event.key === 'Escape') {
      editing = false;
    }
  }
</script>

{#if editing}
<div class="hdr-title" data-task-manager-title={item.id}>
  <span class="tkm-title-label">{t('cplug.huddle.title.label')}</span>
  <input class="oc-field tkm-title-input" use:baseField type="text" maxlength={MAX_TITLE} bind:value={draft} onkeydown={onKeydown}
         placeholder={t('cplug.huddle.title.placeholder')} aria-label={t('cplug.huddle.title.placeholder')} data-task-manager-title-input={item.id} />
  <div class="tkm-title-actions">
    <button type="button" class="oc-btn oc-btn--sm" onclick={() => (editing = false)}>{t('cplug.huddle.row.note_cancel')}</button>
    <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" data-task-manager-title-save={item.id} onclick={() => void commit()}>{t('cplug.huddle.row.note_save')}</button>
  </div>
</div>
{/if}

<style>
  @layer components {
    .hdr-title {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding-left: 8px;
      box-shadow: inset 1px 0 0 var(--oc-orange-dim);
    }

    .tkm-title-label {
      display: block;
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      line-height: 16px;
      text-transform: uppercase;
    }

    .tkm-title-input {
      width: 100%;
      padding: 2px 6px;
      font-size: var(--hd-fs, var(--oc-fs-label));
    }

    .tkm-title-actions {
      display: flex;
      justify-content: flex-end;
      gap: 4px;
    }
  }
</style>
