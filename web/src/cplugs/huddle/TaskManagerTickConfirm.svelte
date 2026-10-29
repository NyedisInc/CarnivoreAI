<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../sdk';
  import { closeTickConfirm, confirmTick, tickConfirm, uncheckedCount } from './task-manager-tick-confirm.svelte';
  import { rowTitle } from './huddle-density';

  const item = $derived(tickConfirm.item);
  const stem = $derived(tickConfirm.mode === 'delete' ? 'cplug.huddle.delete_confirm' : tickConfirm.mode === 'checks' ? 'cplug.huddle.checks_confirm' : 'cplug.huddle.tick_confirm');
  let confirmBtn = $state<HTMLElement | null>(null);

  $effect(() => {
    if (tickConfirm.open) void tick().then(() => confirmBtn?.focus());
  });

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      closeTickConfirm();
    } else if (event.key === 'Enter' && !event.isComposing && !(event.target instanceof HTMLButtonElement)) {
      event.preventDefault();
      void confirmTick();
    }
  }
</script>

{#if tickConfirm.open && item}
  <div class="htc popup-focus" role="dialog" tabindex="-1" aria-label={t(`${stem}.title`)} data-task-manager-tick-confirm={item.id} data-task-manager-confirm-mode={tickConfirm.mode} onkeydown={onKeydown}>
    <div class="htc-titlerow"><span class="htc-label">{t(`${stem}.title`)}</span></div>
    <div class="htc-body">
      <p class="htc-item">{rowTitle(item)}</p>
      <p class="htc-ask" data-task-manager-checks-ask={tickConfirm.mode === 'checks' ? '' : undefined}>{t(`${stem}.ask`, { count: uncheckedCount(item) })}</p>
    </div>
    <footer class="htc-foot">
      <button type="button" class="modal-btn modal-btn-secondary" data-task-manager-tick-cancel onclick={closeTickConfirm}>{t('cplug.huddle.row.note_cancel')}</button>
      <button type="button" class={tickConfirm.mode === 'delete' ? 'modal-btn modal-btn-danger' : 'modal-btn modal-btn-confirm'} bind:this={confirmBtn}
              data-task-manager-tick-confirm-yes onclick={() => void confirmTick()}>{t(`${stem}.submit`)}</button>
    </footer>
  </div>
{/if}

<style>
  @layer components {
    .htc {
      position: fixed;
      top: 50%;
      left: 50%;
      z-index: 60;
      display: flex;
      flex-direction: column;
      width: min(22rem, calc(100vw - var(--oc-space-5)));
      max-height: calc(100vh - var(--oc-space-5));
      margin: 0;
      padding: 0;
      border-radius: var(--oc-radius-sm);
      overflow: auto;
      transform: translate(-50%, -50%);
    }

    .htc-titlerow {
      display: flex;
      align-items: center;
      min-height: var(--oc-space-5);
      padding: 0 var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .htc-label {
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .htc-body {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      padding: var(--oc-space-3);
    }

    .htc-item {
      margin: 0;
      overflow-wrap: anywhere;
    }

    .htc-ask {
      margin: 0;
      color: var(--oc-text-dim);
    }

    .htc-foot {
      display: flex;
      justify-content: flex-end;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2) var(--oc-space-3);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }
  }
</style>
