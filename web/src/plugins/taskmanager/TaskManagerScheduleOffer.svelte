<script lang="ts">
  import { Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import { acceptSchedule } from './huddle.svelte';
  import { submitNow } from './task-submit';
  import { dueLabel } from './task-manager-schedule';
  import type { HuddleItem, TaskManagerMessage } from './huddle-model';

  let { item, message }: { item: HuddleItem; message: TaskManagerMessage } = $props();
  const offer = $derived(message.schedule);
  const accepted = $derived(offer?.state === 'accepted');
  const when = $derived(offer ? dueLabel(Date.parse(offer.when) / 1000, new Date(), { today: t('cplug.huddle.schedule.today'), tomorrow: t('cplug.huddle.schedule.tomorrow') }) : '');
  let pressing = $state(false);

  async function accept(): Promise<void> {
    if (pressing || accepted) return;
    pressing = true;
    try {
      await submitNow(item.list, () => acceptSchedule(item, message.id), { immediate: true });
    } finally {
      pressing = false;
    }
  }
</script>

{#if offer}
  <button type="button" class="hdo" data-task-manager-schedule-offer={message.id} data-state={offer.state} disabled={accepted || pressing}
          title={t(accepted ? 'cplug.huddle.offer.accepted_title' : 'cplug.huddle.offer.title', { title: offer.title, time: when })}
          aria-label={t(accepted ? 'cplug.huddle.offer.accepted_title' : 'cplug.huddle.offer.title', { title: offer.title, time: when })}
          onclick={() => void accept()}>
    <Icon name="clock" size={12} strokeWidth={1.75} />
    <span class="hdo-when">{accepted ? t('cplug.huddle.offer.accepted', { time: when }) : when}</span>
  </button>
{/if}

<style>
  @layer components {
    .hdo {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      align-self: flex-start;
      max-width: 100%;
      margin-top: var(--oc-space-1);
      padding: 0 var(--oc-space-2);
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: var(--oc-space-5);
      cursor: pointer;
    }

    .hdo:hover:not(:disabled) {
      border-color: var(--oc-control-line-hi);
      color: var(--oc-text-primary);
    }

    .hdo[data-state='accepted'] {
      border-color: var(--oc-green);
      color: var(--oc-green);
      cursor: default;
    }

    .hdo-when {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
