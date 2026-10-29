
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import List from '../../base/List.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import State from '../../base/State.svelte';
  import type { Automation } from '../api';
  import { costLabel } from '../format';
  import FoldChevron from '../../../opscenter/ui/FoldChevron.svelte';
  import Mark from '../Mark.svelte';
  import { lookup } from '../feed-store.svelte';
  import { lateBy } from '../logic/feed';
  import { foldRuns } from '../logic/runs-fold';
  import { bytesWords, reasonWords, secsWords, skipSentence, statusWord, tookWords } from '../logic/words';
  import { data, pageClock } from '../page-store.svelte';
  import { loadOlderRuns, pane, type PaneRun } from './pane-data.svelte';

  type Props = { automation: Automation; current: string | null; onOpen: (runId: string) => void };
  let { automation, current, onOpen }: Props = $props();

  let open = $state<Record<string, boolean>>({});
  const groups = $derived(foldRuns(pane.runs, lookup));
  const total = $derived(automation.run_count ?? pane.runs.length);
  const clock = $derived(pageClock());

  function trig(r: PaneRun): string {
    if ((r.attempt ?? 1) > 1) return t('automations.page.pane.runs.trigger_retry', { a: (r.attempt ?? 1) - 1, b: Math.max(1, automation.retry_max) });
    if (r.trigger === 'catch_up') return t('automations.page.trigger.catch_up');
    if (r.trigger === 'run_now') return t('automations.page.trigger.run_now');
    return t('automations.page.pane.runs.trigger_schedule');
  }

  function late(r: PaneRun): string {
    const d = r.trigger === 'schedule' ? lateBy(r) : null;
    return d != null && d >= 1 ? t('automations.page.pane.runs.late_by', { span: secsWords(d) }) : '';
  }

  function words(r: PaneRun): string {
    if (r.status === 'skipped') return skipSentence(r, data.tz);
    return r.reason ? `${statusWord(r.status)}: ${reasonWords(r.reason)}` : statusWord(r.status);
  }

  const cost = (r: PaneRun): string => (r.cost_usd == null ? t('automations.page.pane.runs.not_measured') : costLabel(r.cost_usd));
  const tokens = (r: PaneRun): string => (r.usage ? r.usage.total.toLocaleString('en-US') : t('automations.page.pane.runs.not_measured'));
  const size = (r: PaneRun): string => (r.report_bytes ? bytesWords(r.report_bytes) : t('automations.page.pane.runs.size_none'));
  const took = (r: PaneRun): string => tookWords(r) ?? t('automations.page.pane.runs.took_none');

  function sub(r: PaneRun): string {
    return [trig(r), took(r), r.cost_usd == null ? t('automations.page.pane.runs.cost_not_measured') : cost(r), r.usage ? t('automations.page.pane.runs.tokens_line', { n: tokens(r) }) : '', r.report_bytes ? size(r) : '']
      .filter(Boolean)
      .join(' · ');
  }
</script>

{#snippet row(r: PaneRun, count: number, key: string, member: boolean)}
  {@const lt = late(r)}
  <ListRow wrap data-rr={r.run_id} data-member={member ? '' : undefined} data-folded={count > 1 ? '' : undefined} selected={current === r.run_id}>
    <Button variant="row" data-open-run={r.run_id} aria-label={t('automations.page.pane.runs.open_aria', { n: r.number, words: words(r) })} onclick={() => onOpen(r.run_id)}>
      <span class="ap-rr-b">
        <span class="ap-rr-mk"><Mark status={r.status} size={10} /></span>
        <span class="ap-rr-n ap-num">#{r.number}</span>
        <span class="ap-rr-st ap-num">{clock.when(r.ended_at ?? r.started_at ?? r.slot_at)}{#if lt}<span class="ap-pn-dim"> {lt}</span>{/if}</span>
        <span class="ap-rr-rs" data-run-line>{words(r)}</span>
        <span class="ap-rr-w">{trig(r)}</span>
        <span class="ap-rr-w ap-num">{took(r)}</span>
        <span class="ap-rr-w ap-num">{cost(r)}</span>
        <span class="ap-rr-w ap-num" data-run-tokens>{tokens(r)}</span>
        <span class="ap-rr-w ap-num">{size(r)}</span>
        <span class="ap-rr-sub ap-pn-dim">{sub(r)}</span>
      </span>
    </Button>
    {#snippet actions()}
      {#if count > 1}
        <Button
          variant="quiet"
          size="sm"
          data-fold={key}
          aria-expanded={!!open[key]}
          aria-label={t(open[key] ? 'automations.page.pane.runs.fold_hide' : 'automations.page.pane.runs.fold_show', { n: count })}
          onclick={() => (open[key] = !open[key])}
        >
          <span class="ap-num">x{count}</span><FoldChevron />
        </Button>
      {/if}
    {/snippet}
  </ListRow>
{/snippet}

<Card title={t('automations.page.pane.tab.runs')} compact>
  {#snippet children()}
    {#if pane.status === 'loading' && !pane.runs.length}
      <State kind="loading" inline title={t('automations.loading')} />
    {:else if !pane.runs.length}
      <State inline title={t('automations.page.pane.runs.none')} data-runs-empty />
    {:else}
      <div class="ap-rr-head" aria-hidden="true">
        <span></span><span>{t('automations.page.pane.runs.run')}</span><span>{t('automations.page.pane.runs.started')}</span><span>{t('automations.page.pane.runs.status')}</span><span>{t('automations.page.pane.runs.trigger')}</span><span>{t('automations.page.pane.runs.took')}</span><span>{t('automations.page.pane.runs.cost')}</span><span>{t('automations.page.pane.runs.tokens')}</span><span>{t('automations.page.pane.runs.size')}</span>
      </div>
      <List label={t('automations.page.pane.tab.runs')} data-run-list>
        {#each groups as g (g.head.run_id)}
          {@const key = g.head.run_id}
          {@render row(g.head as PaneRun, g.runs.length, key, false)}
          {#if g.runs.length > 1 && open[key]}
            {#each g.runs.slice(1) as member (member.run_id)}{@render row(member as PaneRun, 1, '', true)}{/each}
          {/if}
        {/each}
      </List>
      <p class="ap-pn-note ap-num" data-runs-loaded>{t('automations.page.pane.runs.loaded', { n: pane.runs.length, total })}</p>
    {/if}
  {/snippet}
  {#snippet foot()}
    {#if pane.runs.length && !pane.exhausted && pane.runs.length < total}
      <Button size="sm" data-load-older disabled={pane.loadingMore} onclick={() => void loadOlderRuns()}>{t('automations.page.pane.runs.load_older')}</Button>
    {/if}
  {/snippet}
</Card>
