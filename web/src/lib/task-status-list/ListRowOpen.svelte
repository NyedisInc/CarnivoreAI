<script lang="ts">
  /* the Task Manager */
  import { t } from '../i18n/index.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { revealInTaskManager } from '../task-manager-reveal/reveal';
  import TaskManagerAsk from '../../plugins/taskmanager/TaskManagerAsk.svelte';
  import TaskManagerAskForm from '../../plugins/taskmanager/ask/TaskManagerAskForm.svelte';
  import TaskManagerMarkdown from '../../plugins/taskmanager/TaskManagerMarkdown.svelte';
  import HuddleReply from '../../plugins/taskmanager/HuddleReply.svelte';
  import { latestMessage } from '../../plugins/taskmanager/huddle-density';
  import { isFormAsk } from '../../plugins/taskmanager/task-manager-posts';
  import { inlineQuestion } from '../../plugins/taskmanager/ask/ask-model';
  import MissingPopup from './MissingPopup.svelte';
  import type { ListRow } from './model';

  let { row, onClose }: { row: ListRow; onClose: () => void } = $props();

  const message = $derived(latestMessage(row.item));
  const typed = $derived(row.status === 'question' && message !== null && isFormAsk(message) && !message.answered && message.id > 0);
  const lone = $derived(typed && message !== null && inlineQuestion(message.form) !== null);
  const replies = $derived(row.status === 'question' || row.status === 'review');
  let failed = $state('');
  let missing = $state(false);

  async function openInTaskManager(): Promise<void> {
    const result = await revealInTaskManager(row.list, row.id);
    missing = result.outcome === 'missing';
    failed = result.reason ?? '';
  }
</script>

<div class="hl-open" data-task-manager-list-open={row.id}>
  {#if typed && message && !lone}
    <TaskManagerAskForm messageId={message.id} mode="cell" {onClose} />
  {:else}
    {#if message}
      <div class="hl-open__words" data-task-manager-list-words>
        {#if row.status === 'question'}<TaskManagerAsk {message} />{:else}<TaskManagerMarkdown text={message.text} />{/if}
      </div>
    {/if}
    {#if replies}<div class="hl-open__reply"><HuddleReply item={row.item} onRow iconSend /></div>{/if}
  {/if}
  {#if failed}<p class="hl-open__failed" role="status" data-task-manager-list-failed>{failed}</p>{/if}
  <div class="hl-open__foot">
    <button type="button" class="oc-ibtn" data-task-manager-list-open-tm aria-label={t('opscenter.cell.task_list.open_in_tm')} title={t('opscenter.cell.task_list.open_in_tm')}
            onclick={() => void openInTaskManager()}><Icon name="external" size={14} /></button>
  </div>
</div>
{#if missing}<MissingPopup onClose={() => (missing = false)} />{/if}

<style>
  @layer components {
    .hl-open {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      padding: 2px var(--oc-space-3) var(--oc-space-3) 28px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      line-height: 1.5;
      min-width: 0;
    }

    .hl-open__words { min-width: 0; overflow-wrap: anywhere; }
    .hl-open__reply { min-width: 0; }
    .hl-open__failed { margin: 0; color: var(--oc-coral); }
    .hl-open__foot { display: flex; justify-content: flex-end; gap: 6px; }
  }
</style>
