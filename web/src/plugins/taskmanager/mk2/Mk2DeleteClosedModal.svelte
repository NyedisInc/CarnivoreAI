<script lang="ts">
  /* it must have a warning */
  import { onMount } from 'svelte';
  import { ModalShell } from '../../sdk/ui';
  import { t } from '../../sdk';
  import { Button } from '../../sdk/ui';

  let { close, count, everywhere = false }: { close: (value: boolean | null) => void; count: number; everywhere?: boolean } = $props();

  let cancel = $state<HTMLElement | null>(null);

  onMount(() => {
    const timer = setTimeout(() => cancel?.focus(), 50);
    return () => clearTimeout(timer);
  });
</script>

<ModalShell look="titlerow" closable={false} title={t('opscenter.cell.task_manager_mk2.delete_closed.title')} overlayClass="mk2-closed-purge" onCancel={() => close(null)}>
  {#snippet children()}
    <p class="mk2-closed-purge__ask" data-mk2-delete-closed-ask>{t(everywhere ? 'opscenter.cell.task_manager_mk2.delete_closed.ask_all' : 'opscenter.cell.task_manager_mk2.delete_closed.ask', { count })}</p>
  {/snippet}
  {#snippet footer()}
    <Button variant="secondary" data-mk2-delete-closed-cancel bind:element={cancel} onclick={() => close(null)}>{t('cplug.huddle.row.note_cancel')}</Button>
    <Button variant="danger" data-mk2-delete-closed-confirm onclick={() => close(true)}>{t('opscenter.cell.task_manager_mk2.delete_closed.confirm', { count })}</Button>
  {/snippet}
</ModalShell>

<style>
  @layer components {
    .mk2-closed-purge__ask {
      margin: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      line-height: 1.5;
    }
  }
</style>
