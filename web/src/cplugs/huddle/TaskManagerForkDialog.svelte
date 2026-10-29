<script lang="ts">
  import { tick } from 'svelte';
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

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeFork();
    } else if (event.key === 'Enter' && !event.isComposing && event.target instanceof HTMLInputElement) {
      event.preventDefault();
      void finish();
    }
  }
</script>

{#if forkDialog.open && item}
  <div class="hfk popup-focus" role="dialog" tabindex="-1" aria-label={t('cplug.huddle.fork.dialog')} data-task-manager-fork-dialog={item.id} onkeydown={onKeydown}>
    <div class="hfk-titlerow"><span class="hfk-label">{t('cplug.huddle.fork.dialog')}</span></div>
    <div class="hfk-body">
      <label class="hfk-field">
        <span class="hfk-label">{t('cplug.huddle.fork.name')}</span>
        <input class="oc-field" use:baseField type="text" maxlength="120" bind:value={draft.title} bind:this={first} placeholder={rowTitle(item)}
               data-task-manager-fork-title={item.id} />
      </label>
      <label class="hfk-field">
        <span class="hfk-label">{t('cplug.huddle.fork.fork_state')}</span>
        <select class="oc-field" bind:value={draft.forkState} data-task-manager-fork-state={item.id}>
          {#each FORK_STATES as state (state)}<option value={state}>{t(stateKey(state))}</option>{/each}
        </select>
      </label>
      <label class="hfk-field">
        <span class="hfk-label">{t('cplug.huddle.fork.parent_state')}</span>
        <select class="oc-field" bind:value={draft.parentState} data-task-manager-fork-parent-state={item.id}>
          <option value="">{t('cplug.huddle.fork.unchanged')}</option>
          {#each FORK_STATES as state (state)}<option value={state}>{t(stateKey(state))}</option>{/each}
        </select>
      </label>
    </div>
    <footer class="hfk-foot">
      <button type="button" class="modal-btn modal-btn-secondary" data-task-manager-fork-close onclick={closeFork}>{t('cplug.huddle.row.note_cancel')}</button>
      <button type="button" class="modal-btn modal-btn-confirm" disabled={busy} data-task-manager-fork-save={item.id}
              onclick={() => void finish()}>{t('cplug.huddle.fork.submit')}</button>
    </footer>
  </div>
{/if}

<style>
  @layer components {
    .hfk {
      position: fixed;
      top: 50%;
      left: 50%;
      z-index: 60;
      display: flex;
      flex-direction: column;
      width: min(26rem, calc(100vw - var(--oc-space-5)));
      max-height: calc(100vh - var(--oc-space-5));
      margin: 0;
      padding: 0;
      border-radius: var(--oc-radius-sm);
      overflow: auto;
      transform: translate(-50%, -50%);
    }

    .hfk-titlerow {
      display: flex;
      align-items: center;
      min-height: var(--oc-space-5);
      padding: 0 var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .hfk-label {
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hfk-body {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-3);
      padding: var(--oc-space-3);
    }

    .hfk-field {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .hfk-foot {
      display: flex;
      justify-content: flex-end;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2) var(--oc-space-3);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }
  }
</style>
