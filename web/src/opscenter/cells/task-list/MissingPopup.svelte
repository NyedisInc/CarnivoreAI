<script lang="ts">
  import AnchoredPopup from '../../../lib/dialog-frame/AnchoredPopup.svelte';
  import { t } from '../../../lib/i18n/index.svelte';

  let { onClose }: { onClose: () => void } = $props();
</script>

<AnchoredPopup class="hl-warn" role="alertdialog" topLayer tabindex={-1} label={t('opscenter.cell.task_list.no_tm')} data-task-manager-list-warn=""
  placement="manual" initialFocus="[data-task-manager-list-warn-ok]" {onClose}>
  <p class="hl-warn__line">{t('opscenter.cell.task_list.no_tm')}</p>
  <div class="hl-warn__row">
    <button type="button" class="modal-btn modal-btn-secondary" data-task-manager-list-warn-ok onclick={onClose}>{t('opscenter.cell.task_list.no_tm_ok')}</button>
  </div>
</AnchoredPopup>

<style>
  @layer components {
    :global(.hl-warn) {
      position: fixed;
      inset: 20vh auto auto 50%;
      transform: translateX(-50%);
      margin: 0;
      width: min(320px, calc(100vw - 16px));
      display: grid;
      gap: var(--oc-space-2);
      padding: var(--oc-space-3);
      box-sizing: border-box;
      background: var(--oc-ground-panel);
      border: var(--oc-border) solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-primary);
    }

    .hl-warn__line {
      margin: 0;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      line-height: 1.45;
    }

    .hl-warn__row { display: flex; justify-content: flex-end; }
  }
</style>
