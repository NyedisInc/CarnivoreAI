
<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import List from '../../base/List.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import State from '../../base/State.svelte';
  import { reports, lookup } from '../feed-store.svelte';
  import { compare, previousIndex, type DiffRun } from '../logic/diff';
  import { slotOf, type FeedRow } from '../logic/feed';
  import { skipReason, statusWord } from '../logic/words';
  import { data, openDrawer, openInAdvanced } from '../page-store.svelte';
  import { attachmentRows, sinceSentence } from './drawer-model';
  import { dr, loadRun } from './drawer-state.svelte';
  import LastRun from './LastRun.svelte';

  let { id }: { id: string } = $props();

  const mine = $derived(dr.key === `run:${id}`);
  const run = $derived(mine ? dr.run : null);
  const name = $derived(run ? (data.automations.find((a) => a.automation_id === run.automation_id)?.name ?? '') : '');
  const attachments = $derived(attachmentRows(run?.attachments));

  const since = $derived.by(() => {
    if (!run) return '';
    if (run.status === 'skipped') return skipReason(run, data.tz);
    if (run.status !== 'succeeded' && run.status !== 'failed') return t('automations.simple.dr.nothing_compare');
    void reports[run.run_id];
    const at = dr.runs.findIndex((r) => r.run_id === run.run_id);
    const prev = at >= 0 ? previousIndex(dr.runs, at, lookup) : -1;
    const base = prev >= 0 ? (dr.runs[prev] as FeedRow) : null;
    if (!base) return t('automations.simple.dr.nothing_compare');
    const result = compare({ run: base as unknown as DiffRun, slot: slotOf(base, lookup) }, { run: run as unknown as DiffRun, slot: slotOf(run as FeedRow, lookup) }, { statusWord });
    return sinceSentence(result) || t('automations.simple.dr.nothing_compare');
  });

  $effect(() => {
    const runId = id;
    if (data.fixture) return;
    untrack(() => void loadRun(runId));
  });
</script>

{#if !mine || dr.status === 'loading'}
  <Card title={t('automations.simple.dr.label_run')} compact>
    {#snippet children()}<State kind="loading" inline title={t('automations.loading')} data-dr-loading />{/snippet}
  </Card>
{:else if dr.status === 'error' || !run}
  <Card title={t('automations.simple.dr.label_run')} compact>
    {#snippet children()}<State kind="error" inline title={`${t('automations.simple.read_failed')}: ${dr.error}`} data-dr-failed />{/snippet}
    {#snippet foot()}<Button size="sm" onclick={() => void loadRun(id)}>{t('automations.simple.retry')}</Button>{/snippet}
  </Card>
{:else}
  <LastRun {run} title={t('automations.simple.dr.label_run')} heading size={14} />

  <Card title={t('automations.simple.dr.automation')} compact>
    {#snippet children()}<div class="ap-dr-title">{name}</div>{/snippet}
    {#snippet foot()}
      <Button size="sm" data-dr-auto={run.automation_id} onclick={() => openDrawer('automation', run.automation_id)}>{t('automations.simple.dr.open_automation')}</Button>
    {/snippet}
  </Card>

  <Card title={t('automations.simple.dr.changed')} compact>
    {#snippet children()}<p class="ap-dr-sum" data-dr-since>{since}</p>{/snippet}
  </Card>

  {#if attachments.length}
    <Card title={t('automations.simple.dr.attachments')} compact>
      {#snippet children()}
        <List label={t('automations.simple.dr.attachments')} data-dr-attachments>
          {#each attachments as file, i (i)}<ListRow primary={file.name} meta={file.size} />{/each}
        </List>
      {/snippet}
    </Card>
  {/if}

  <Card title={t('automations.simple.dr.full_report')} compact>
    {#snippet children()}<p class="t-quiet">{t('automations.simple.dr.full_report_note')}</p>{/snippet}
    {#snippet foot()}
      <Button size="sm" data-dr-adv-run={run.run_id} onclick={() => openInAdvanced('run', run.run_id)}>{t('automations.simple.dr.full_report')}</Button>
    {/snippet}
  </Card>
{/if}
