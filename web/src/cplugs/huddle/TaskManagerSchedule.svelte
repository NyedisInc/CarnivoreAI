<script lang="ts">
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import TaskManagerScheduleKeys from './TaskManagerScheduleKeys.svelte';
  import { openScheduleEditor } from './task-manager-schedule-editor.svelte';
  import { dueLabel, dueState, repeatLabel } from './task-manager-schedule';
  import type { HuddleItem } from './huddle-model';

  let { item }: { item: HuddleItem } = $props();

  const trigger = $derived(item.start_trigger ?? null);
  const repeat = $derived(trigger?.repeat ?? null);
  const phase = $derived(dueState(item));
  const words = $derived({ today: t('cplug.huddle.schedule.today'), tomorrow: t('cplug.huddle.schedule.tomorrow') });
  const shown = $derived(trigger ? dueLabel(trigger.fire_at, new Date(), words) : '');
  const repeatText = $derived(repeat ? repeatLabel(repeat, t) : '');

</script>

{#if trigger}
<div class="tkm-sched" data-task-manager-schedule={item.id} data-due-state={phase ?? undefined}>
  <span class="tkm-sched-label">{t('cplug.huddle.schedule.label')}</span>
  <span class="tkm-sched-line">
    {#if repeat}<span class="tkm-sched-repeat-icon" data-task-manager-schedule-repeat={item.id}><Icon name="cycle" size={11} /></span>{/if}
    <button type="button" class="tkm-sched-show" data-task-manager-schedule-edit={item.id}
            onclick={() => openScheduleEditor(item.list, item)}>{repeat ? `${repeatText}${trigger.paused ? '' : `, ${t('cplug.huddle.schedule.next', { time: shown })}`}` : shown}</button>
    <TaskManagerScheduleKeys {item} />
  </span>
  {#if phase === 'paused'}<span class="tkm-sched-note" data-task-manager-schedule-paused={item.id}>{t('cplug.huddle.schedule.paused_note')}</span>{/if}
  {#if phase === 'fired'}<span class="tkm-sched-note" data-task-manager-schedule-sent={item.id}>{t('cplug.huddle.schedule.sent')}</span>{/if}
  {#if phase === 'failed' && trigger.last_error}<span class="tkm-sched-note tkm-sched-note--failed" data-task-manager-schedule-error={item.id}>{trigger.last_error}</span>{/if}
</div>
{/if}

<style>
  @layer components {
    .tkm-sched {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding-left: 8px;
      box-shadow: inset 1px 0 0 var(--oc-orange-dim);
    }

    .tkm-sched-label {
      display: block;
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      line-height: 16px;
      text-transform: uppercase;
    }

    .tkm-sched-line {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    .tkm-sched-show {
      padding: 0;
      border: 1px solid transparent;
      background: none;
      color: var(--oc-text-primary);
      font: inherit;
      line-height: 1.5;
      text-align: left;
      cursor: pointer;
    }






    .tkm-sched-repeat-icon {
      display: inline-flex;
      color: var(--oc-text-muted);
    }



    .tkm-sched-note {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .tkm-sched-note--failed {
      color: var(--oc-coral);
    }
  }
</style>
