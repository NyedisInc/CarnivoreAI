<script lang="ts">
  /* all session tasks */
  import Icon from '../../ui/Icon.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import type { TaskItem } from '../../api/session-tasks.svelte';

  let { tasks }: { tasks: readonly TaskItem[] } = $props();
</script>

<ul class="oc-tsk-list" aria-label={t('opscenter.cell.tasks.list')}>
  {#each tasks as task (task.id)}
    <li class="oc-tsk-row" data-task-status={task.status}>
      <span class="oc-tsk-mark" role="img" aria-label={t(`opscenter.cell.tasks.status.${task.status}`)}>
        {#if task.status === 'completed'}<Icon name="check" size={10} strokeWidth={2.5} />{/if}
      </span>
      <span class="oc-tsk-text">{task.status === 'in_progress' && task.active_form ? task.active_form : task.subject}</span>
    </li>
  {/each}
</ul>

<style>
  @layer components {
    .oc-tsk-list { list-style: none; margin: 0; padding: 0; }

    .oc-tsk-row { display: flex; align-items: flex-start; gap: var(--oc-space-1-5); min-width: 0; padding: calc(var(--oc-space-1) - var(--oc-border)) var(--oc-space-1-5) var(--oc-space-1) var(--oc-space-1); font-family: var(--font-mono); font-size: var(--oc-fs-body); line-height: 16px; }

    .oc-tsk-mark { flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; width: 12px; height: 12px; margin-top: var(--oc-space-0-5); border: 1px solid var(--oc-text-dim); border-radius: var(--oc-radius-sm); color: var(--oc-text-dim); }

    .oc-tsk-text { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }

    .oc-tsk-row[data-task-status='in_progress'] .oc-tsk-mark { border-color: var(--oc-green); background: var(--oc-green); }

    .oc-tsk-row[data-task-status='in_progress'] .oc-tsk-text { color: var(--oc-green); }

    .oc-tsk-row[data-task-status='completed'] .oc-tsk-text { color: var(--oc-text-dim); text-decoration: line-through; }
  }
</style>
