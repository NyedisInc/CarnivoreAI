<script lang="ts">
  import { ModalShell, TaskStatusList } from '../sdk/ui';
  import { t } from '../sdk';
    
  let { close, list, heading, kind, label, count = null, marked = false, hide = false }: {
    close: (value: null) => void; list: string; heading: string; kind: string; label: string; count?: number | null; marked?: boolean; hide?: boolean;
  } = $props();

  const title = $derived(count === null ? `${heading} \u00b7 ${label}` : `${heading} \u00b7 ${label} \u00b7 ${count}`);
</script>

<ModalShell {title} overlayClass="text-prompt-modal hd-status-modal" onCancel={() => close(null)}>
  {#snippet head()}
    <div class="text-prompt-modal__head" data-task-manager-status-modal-head><span class="text-prompt-modal__verb hd-status-modal__label">{title}</span></div>
  {/snippet}
  {#snippet children()}
    <div class="hd-status-modal__list" data-task-manager-status-modal={kind} data-task-manager-status-modal-list={list}>
      <TaskStatusList {list} {kind} {marked} {hide} />
    </div>
  {/snippet}
  {#snippet footer()}
    <button type="button" class="modal-btn modal-btn-secondary" data-task-manager-status-modal-close onclick={() => close(null)}>{t('modal.close')}</button>
  {/snippet}
</ModalShell>

<style>
  @layer components {
    .hd-status-modal__label {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hd-status-modal__list {
      max-height: min(60vh, 28rem);
      overflow-y: auto;
    }
  }
</style>
