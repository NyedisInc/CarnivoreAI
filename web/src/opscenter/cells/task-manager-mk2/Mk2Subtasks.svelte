<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import { itemsOnScreen } from '../../../cplugs/huddle/huddle.svelte';
  import { stepsOfItem } from '../../../cplugs/huddle/task-manager-steps.svelte';
  import { jumpToParent } from '../../../cplugs/huddle/task-manager-fork.svelte';
  import TaskManagerForkedFrom from '../../../cplugs/huddle/TaskManagerForkedFrom.svelte';
  import TaskManagerSteps from '../../../cplugs/huddle/TaskManagerSteps.svelte';
  import { subtasksOf } from './mk2-subtasks';

  let { item }: { item: HuddleItem } = $props();

  const rows = $derived(subtasksOf(item.id, itemsOnScreen()));
  const steps = $derived(stepsOfItem(item.list, item.id));
</script>

<div class="mk2-subtasks" data-mk2-subtasks>
  <TaskManagerForkedFrom {item} />
  <TaskManagerSteps entry={steps} open />
  {#each rows as row (row.id)}
    <button type="button" class="mk2-sub" data-btn="row" data-mk2-subtask={row.id} onclick={() => jumpToParent(row.id)}>
      <span class="mk2-sub-title">{row.title}</span>
      <span class="mk2-sub-status" data-mk2-subtask-status>{t(row.statusKey)}</span>
      <span class="mk2-sub-owner" data-mk2-subtask-owner>{row.owner}</span>
    </button>
  {:else}
    <p class="mk2-sub-none" data-mk2-subtasks-none>{t('opscenter.cell.task_manager_mk2.subtasks_none')}</p>
  {/each}
</div>

<style>
  @layer components {
    .mk2-subtasks {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    .mk2-sub {
      --_btn-h: 0px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: var(--oc-space-2);
      align-items: baseline;
      min-width: 0;
      padding: var(--oc-space-1) 0;
      border: 0;
      background: none;
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
      color: var(--oc-text-primary);
      font: inherit;
      text-align: left;
      cursor: pointer;
    }

    .mk2-sub:hover {
      background: var(--oc-orange-tint);
    }

    .mk2-sub-title {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .mk2-sub-status,
    .mk2-sub-owner {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .mk2-sub-none {
      margin: 0;
      color: var(--oc-text-muted);
    }
  }
</style>
