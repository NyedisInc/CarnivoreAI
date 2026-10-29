<script lang="ts">
  import { t } from '../sdk';
  import { Button } from '../sdk/ui';
  import { saveSchedule } from './huddle.svelte';
  import type { HuddleItem } from './huddle-model';

  let { item }: { item: HuddleItem } = $props();

  const trigger = $derived(item.start_trigger ?? null);
  const repeat = $derived(trigger?.repeat ?? null);

  async function stopSchedule(): Promise<void> {
    await saveSchedule(item, { fire_at: '' });
  }

  async function togglePause(): Promise<void> {
    await saveSchedule(item, { paused: !trigger?.paused });
  }
</script>

{#if trigger}
  {#if repeat}
    <Button size="sm" data-task-manager-schedule-pause={item.id} onclick={(event: MouseEvent) => { event.stopPropagation(); void togglePause(); }}>{t(trigger.paused ? 'cplug.huddle.schedule.resume' : 'cplug.huddle.schedule.pause')}</Button>
  {/if}
  <Button size="sm" data-task-manager-schedule-cancel={item.id} onclick={(event: MouseEvent) => { event.stopPropagation(); void stopSchedule(); }}>{t(repeat ? 'cplug.huddle.schedule.stop' : 'cplug.huddle.schedule.cancel')}</Button>
{/if}
