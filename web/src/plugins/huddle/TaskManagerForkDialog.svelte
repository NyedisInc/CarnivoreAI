<script lang="ts">
  import { tick } from 'svelte';
  import { ModalShell } from '../sdk/ui';
  import { baseField } from './task-manager-base-field';
  import { t } from '../sdk';
  import { closeFork, forkDialog, submitFork } from './task-manager-fork.svelte';
  import { FORK_STATES, forkDraft, type ForkDraft } from './task-manager-fork';
  import { stateKey } from './huddle-model';
  import { rowTitle } from './huddle-density';

  const item = $derived(forkDialog.item);
  let draft = $state<ForkDraft>(forkDraft({}));
  let busy = $state(false);
  let first = $state<HTMLElement | null>(null);

  $effect(() => {
    if (!forkDialog.open || !item) return;
    draft = forkDraft(item);
    busy = false;
    void tick().then(() => first?.focus());
  });

  async function finish(): Promise<void> {
    if (busy) return;
    busy = true;
    const done = await submitFork(draft);
    busy = false;
    if (done) closeFork();
  }

  function onTitleKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' || event.isComposing) return;
    event.preventDefault();
    void finish();
  }
</script>

{#if forkDialog.open && item}
  <ModalShell look="titlerow" title={t('cplug.huddle.fork.dialog')} onCancel={closeFork} data-task-manager-fork-dialog={item.id}>
    <div class="hfk-body">
      <label class="hfk-field">
        <span class="modal-label">{t('cplug.huddle.fork.name')}</span>
        <input class="oc-field" use:baseField type="text" maxlength="120" bind:value={draft.title} bind:this={first} placeholder={rowTitle(item)}
               data-task-manager-fork-title={item.id} onkeydown={onTitleKeydown} />
      </label>
      <label class="hfk-field">
        <span class="modal-label">{t('cplug.huddle.fork.fork_state')}</span>
        <select class="oc-field" bind:value={draft.forkState} data-task-manager-fork-state={item.id}>
          {#each FORK_STATES as state (state)}<option value={state}>{t(stateKey(state))}</option>{/each}
        </select>
      </label>
      <label class="hfk-field">
        <span class="modal-label">{t('cplug.huddle.fork.parent_state')}</span>
        <select class="oc-field" bind:value={draft.parentState} data-task-manager-fork-parent-state={item.id}>
          <option value="">{t('cplug.huddle.fork.unchanged')}</option>
          {#each FORK_STATES as state (state)}<option value={state}>{t(stateKey(state))}</option>{/each}
        </select>
      </label>
    </div>
    {#snippet footer()}
      <button type="button" class="modal-btn modal-btn-secondary" data-task-manager-fork-close onclick={closeFork}>{t('cplug.huddle.row.note_cancel')}</button>
      <button type="button" class="modal-btn modal-btn-confirm" disabled={busy} data-task-manager-fork-save={item.id}
              onclick={() => void finish()}>{t('cplug.huddle.fork.submit')}</button>
    {/snippet}
  </ModalShell>
{/if}

<style>
  @layer components {
    .hfk-body {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-3);
    }

    .hfk-field {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      min-width: 0;
    }
  }
</style>
