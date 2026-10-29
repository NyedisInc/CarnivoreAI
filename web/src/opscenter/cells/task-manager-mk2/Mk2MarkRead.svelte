<script lang="ts">
  import Button from '../../../lib/base/Button.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import { clock, startClock } from '../../lib/frozen-clock.svelte';
  import { holdLeft, pressMarkRead } from './mk2-mark-read.svelte';

  let { item }: { item: HuddleItem } = $props();
  $effect(() => startClock());
  const left = $derived((void clock.now, holdLeft(item.id)));
</script>

{#if item.unread || left !== null}
  <Button size="sm" onclick={() => pressMarkRead(item)} title={t(left === null ? 'cplug.huddle.thread.mark_read_title' : 'opscenter.cell.task_manager_mk2.mark_read_undo_title')}
          data-task-manager-mark-read={item.id} data-mk2-mark-read-left={left ?? undefined}>{left === null ? t('cplug.huddle.thread.mark_read') : t('opscenter.cell.task_manager_mk2.mark_read_undo', { n: left })}</Button>
{/if}
