<script lang="ts">
  import { t } from '../sdk';
  import { baseField } from './task-manager-base-field';
  import { createGroup } from './task-manager-groups.svelte';

  let { target, onClose }: { target: string; onClose: () => void } = $props();

  let draft = $state('');

  async function make(): Promise<void> {
    const name = draft.trim();
    if (name && !(await createGroup(target, name))) return;
    onClose();
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      onClose();
    }
  }
</script>

<form class="hdg" onsubmit={(event) => { event.preventDefault(); void make(); }}>
  <!-- svelte-ignore a11y_autofocus -->
  <input class="oc-field hdg-input" use:baseField type="text" maxlength="80" bind:value={draft} autofocus onkeydown={onKey}
         placeholder={t('cplug.huddle.group.name_placeholder')} aria-label={t('cplug.huddle.group.name_placeholder')} data-task-manager-group-name />
  <button type="button" class="oc-btn oc-btn--sm oc-btn--ghost" onclick={onClose} data-task-manager-group-cancel>{t('cplug.huddle.group.cancel')}</button>
  <button type="submit" class="oc-btn oc-btn--sm" disabled={!draft.trim()} data-task-manager-group-create>{t('cplug.huddle.group.create')}</button>
</form>

<style>
  @layer components {
    .hdg {
      display: flex;
      flex: 1 1 auto;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .hdg-input {
      flex: 1 1 auto;
      min-width: 0;
      height: 20px;
      padding: 0 6px;
      font-size: var(--oc-fs-label);
      line-height: 18px;
    }
  }
</style>
