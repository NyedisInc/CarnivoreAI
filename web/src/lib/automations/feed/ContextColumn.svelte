
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import List from '../../base/List.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import * as api from '../api';
  import { ensureReport, lookup, reports } from '../feed-store.svelte';
  import Mark from '../Mark.svelte';
  import { usableReport } from '../logic/diff';
  import { slotOf, type FeedRow } from '../logic/feed';
  import { face } from '../logic/report-rules';
  import type { FeedRun } from '../logic/types';
  import { isLive, runTime, type Clock } from '../logic/words';
  import { compactLines, dayOf } from './feed-model';

  type Props = { automationId: string; name: string; currentRunId: string | null; refreshKey: string; clock: Clock; tz: string; now: number; onPick: (runId: string) => void };
  let { automationId, name, currentRunId, refreshKey, clock, tz, now, onPick }: Props = $props();

  const WIDE_PX = 1700;
  let wide = $state(typeof window !== 'undefined' && window.innerWidth >= WIDE_PX);
  let list = $state<FeedRun[]>([]);
  let loaded = '';

  onMount(() => {
    const onResize = (): void => {
      wide = window.innerWidth >= WIDE_PX;
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  });

  async function load(id: string): Promise<void> {
    try {
      const page = await api.listRuns(id, 12, { include_report: true });
      if (loaded !== `${id}|${refreshKey}`) return;
      for (const run of page.runs) {
        if (!run.has_report || isLive(run.status) || reports[run.run_id]) continue;
        if (run.report_omitted || !('report' in run)) ensureReport(run.run_id);
        else reports[run.run_id] = { state: 'ready', report: run.report ?? null };
      }
      list = page.runs as unknown as FeedRun[];
    } catch {
    }
  }

  $effect(() => {
    if (!wide || !automationId) return;
    loaded = `${automationId}|${refreshKey}`;
    void load(automationId);
  });

  function lines(run: FeedRun, i: number): string[] {
    const slot = slotOf(run as FeedRow, lookup);
    const prevRun = list[i + 1];
    const prevReport = prevRun ? (usableReport(slotOf(prevRun as FeedRow, lookup)) ?? null) : null;
    const f = face(run as FeedRow, slot, { clock, tz, now, prevReport });
    return compactLines(run, f.text, usableReport(slot), prevReport, 2);
  }
</script>

<aside class="ap-cx" data-context-column aria-label={t('automations.page.reader.ctx.title')}>
  {#if automationId}
    <Card title={t('automations.page.reader.ctx.title')} meta={name} compact>
      {#snippet children()}
        <List label={t('automations.page.reader.ctx.title')}>
          {#each list as r, i (r.run_id)}
            <ListRow wrap selected={r.run_id === currentRunId}>
              <Button variant="row" data-pick-run={r.run_id} data-status={r.status} aria-current={r.run_id === currentRunId ? 'true' : undefined} onclick={() => onPick(r.run_id)}>
                <span class="ap-cx-r">
                  <span class="ap-cx-t ap-num"><Mark status={r.status} size={10} /> #{r.number} · {dayOf(runTime(r), tz)} {clock.hm24(runTime(r))}</span>
                  <span class="r-compact">{#each lines(r, i) as l (l)}<span>{l}</span>{/each}</span>
                </span>
              </Button>
            </ListRow>
          {/each}
        </List>
      {/snippet}
    </Card>
  {/if}
</aside>
