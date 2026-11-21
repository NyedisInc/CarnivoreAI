<script lang="ts">
  import { ModalShell } from '../../sdk/ui';
  import { t } from '../../sdk';
  import TaskManagerAskForm from './TaskManagerAskForm.svelte';

  let { messageId, close }: { messageId: number; close: (value: null) => void } = $props();
</script>

<ModalShell title={t('cplug.huddle.ask.label')} overlayClass="hdq-modal" onCancel={() => close(null)}>
  {#snippet head()}{/snippet}
  {#snippet footer()}{/snippet}
  <TaskManagerAskForm {messageId} mode="panel" onClose={() => close(null)} />
</ModalShell>
