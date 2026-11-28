<script lang="ts">
  import { t } from '../sdk';
  import { waitLine } from './task-manager-wait';
  import type { HuddleItem } from './huddle-model';

  let { item }: { item: HuddleItem } = $props();

  const line = $derived(waitLine(item, new Date(), { t, due: { today: t('cplug.huddle.schedule.today'), tomorrow: t('cplug.huddle.schedule.tomorrow') } }));
</script>

{#if line.on}
  <p class="tkm-wait" data-task-manager-wait={item.id} title={t(line.hold ? 'cplug.huddle.wait.forks_tip' : 'cplug.huddle.wait.tip')}>
    <span class="tkm-wait-on">{line.on}</span>
    {#if line.check}<span class="tkm-wait-note" data-task-manager-wait-check={item.id}>{line.check}</span>{/if}
    {#if line.extended}<span class="tkm-wait-note" data-task-manager-wait-extended={item.id}>{line.extended}</span>{/if}
    {#if line.asked}<span class="tkm-wait-note" data-task-manager-wait-asked={item.id}>{t('cplug.huddle.wait.asked')}</span>{/if}
  </p>
{/if}

<style>
  @layer components {
    .tkm-wait {
      display: flex;
      flex-wrap: wrap;
      gap: var(--oc-space-1) var(--oc-space-3);
      align-self: flex-start;
      min-width: 0;
      max-width: 100%;
      margin: 0;
      padding: 0 var(--oc-space-2);
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: var(--oc-space-5);
    }

    .tkm-wait-on {
      min-width: 0;
      overflow-wrap: anywhere;
    }

    .tkm-wait-note {
      color: var(--oc-text-muted);
    }
  }
</style>
