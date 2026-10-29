
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import type { RunSummary } from '../api';
  import { lookup, ensureReport } from '../feed-store.svelte';
  import { isUnread, slotOf, type FeedRow } from '../logic/feed';
  import { face } from '../logic/report-rules';
  import { runTime, tookWords } from '../logic/words';
  import Mark from '../Mark.svelte';
  import { data, openDrawer, pageClock } from '../page-store.svelte';
  import { markRead, unread } from '../read-state.svelte';
  import { runWord } from '../review/review-model';
  import { runWords } from './drawer-model';

  let { run, title, openable = false, heading = false, size = 12 }: { run: RunSummary; title: string; openable?: boolean; heading?: boolean; size?: number } = $props();

  const clock = $derived(pageClock());
  const reviewed = $derived(!isUnread(run, { seenAt: unread.seenAt, read: new Set(unread.read) }, data.now));
  const slot = $derived(slotOf(run, lookup));
  const words = $derived(runWords(run, face(run as FeedRow, slot, { clock, tz: data.tz, now: data.now }).text));
  const took = $derived(tookWords(run));
  const facts = $derived([clock.when(runTime(run)), took ? t('automations.simple.dr.took', { took }) : ''].filter(Boolean).join(' · '));

  $effect(() => {
    if (!run.title && run.has_report && slot.state === 'pending') ensureReport(run.run_id);
  });
</script>

<Card title={title} compact>
  {#snippet children()}
    <div class="ap-dr-st">
      <Mark status={run.status} {size} /><b>{t(`automations.simple.row.word.${runWord(run).key}`)}</b><span class="t-quiet">{facts}</span>
    </div>
    <svelte:element this={heading ? 'h2' : 'div'} class={heading ? 'ap-dr-name' : 'ap-dr-title'} data-dr-title>{words.title}</svelte:element>
    {#if words.summary}<p class="ap-dr-sum" data-dr-summary>{words.summary}</p>{/if}
    {#if reviewed}<span class="t-quiet">{t('automations.simple.row.reviewed')}</span>{/if}
  {/snippet}
  {#snippet foot()}
    {#if !reviewed}
      <Button size="sm" data-dr-good={run.run_id} onclick={() => markRead([run.run_id])}>{t('automations.simple.row.good')}</Button>
    {/if}
    {#if openable}
      <Button size="sm" data-dr-open-run={run.run_id} onclick={() => openDrawer('run', run.run_id)}>{t('automations.simple.dr.open_run')}</Button>
    {/if}
  {/snippet}
</Card>
