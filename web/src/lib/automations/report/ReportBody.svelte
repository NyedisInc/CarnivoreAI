
<script lang="ts">
  import Button from '../../base/Button.svelte';
  import Card from '../../base/Card.svelte';
  import StatTile from '../../base/StatTile.svelte';
  import State from '../../base/State.svelte';
  import { getContext } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import { isEmpty, isObj } from '../logic/diff';
  import { wordMark } from '../logic/marks';
  import { bodyPlan, emptyStatement, type FaceRun, type RuleContext } from '../logic/report-rules';
  import { tookWords } from '../logic/words';
  import LongText from './LongText.svelte';
  import { mark, REPORT_CTX, type ReportCtx } from './ReportTree.svelte';
  import ReportTree from './ReportTree.svelte';
  import Tiles from './Tiles.svelte';

  interface Props {
    run: FaceRun & { ended_at: number | null; report_bytes: number | null };
    report: unknown;
    prevReport?: unknown;
    rules: RuleContext;
    sessions?: number;
  }
  let { run, report, prevReport = null, rules, sessions = 0 }: Props = $props();
  const ctx = getContext<ReportCtx | undefined>(REPORT_CTX);

  const object = $derived(isObj(report) ? report : null);
  const plan = $derived(object ? bodyPlan(run, object, prevReport) : []);
  const bare = $derived(report !== null && report !== undefined && !object && !isEmpty(report));
  const empty = $derived(!bare && (!object || !plan.length) ? emptyStatement(run, report, tookWords(run), sessions, rules) : null);
  const findingOf = (i: number): string | null => {
    const it = object && Array.isArray(object.items) ? (object.items[i] as Record<string, unknown> | undefined) : undefined;
    return it && typeof it.finding_id === 'string' && it.finding_id ? it.finding_id : null;
  };
</script>

{#if empty}
  <State kind="empty" inline title={empty.text} hint={empty.facts.length ? empty.facts.join(', ') : undefined} data-status={run.status} />
{:else if bare}
  <Card title={t('automations.page.report.fields')}><ReportTree value={report} /></Card>
{:else}
  {#each plan as s, n (n)}
    {#if s.kind === 'summary'}
      <div class="r-summary"><LongText text={s.text} truncated={ctx?.truncated ?? false} /></div>
    {:else if s.kind === 'exit_code'}
      <div class="r-exit" data-key="exit_code">
        <StatTile label={t('automations.page.report.exit_code')} figure={String(s.code)} sub={s.zero ? t('automations.page.report.zero') : t('automations.page.report.non_zero')}>
          {#snippet icon()}{@render mark(s.zero ? 'succeeded' : 'failed', 12, s.zero ? t('automations.page.report.zero') : t('automations.page.report.non_zero'))}{/snippet}
        </StatTile>
      </div>
    {:else if s.kind === 'tiles'}
      <Tiles tiles={s.tiles} />
    {:else if s.kind === 'stream'}
      <Card title={t(`automations.page.report.${s.name}`)} data-stream={s.name}>
        <LongText text={s.text} truncated={ctx?.truncated ?? false} />
      </Card>
    {:else if s.kind === 'quiet'}
      <div class="r-note r-quiet">{t('automations.page.report.quiet')}</div>
    {:else if s.kind === 'items'}
      <Card title={t('automations.page.report.items')} meta={String(s.items.length)}>
        <ul class="r-items">
          {#each s.items as it, i (i)}
            {@const fid = ctx?.fix && it.fix_prompt ? findingOf(i) : null}
            <li>
              {@render mark(wordMark(it.status) ?? 'neutral', 10, String(it.status ?? 'none'))}
              <span class="r-il">{it.label}</span>
              {#if it.detail}<span class="r-id">{it.detail}</span>{/if}
              {#if fid}<Button size="sm" data-fix={fid} onclick={() => ctx?.fix?.(fid)}>{t('automations.page.report.fix_it')}</Button>{/if}
            </li>
          {/each}
        </ul>
      </Card>
    {:else if s.kind === 'fields'}
      <Card title={t('automations.page.report.fields')}>
        <ReportTree value={s.fields} />
      </Card>
    {:else if s.kind === 'section'}
      <Card title={s.heading} meta={s.count !== null ? String(s.count) : undefined}>
        <ReportTree value={s.value} keyName={s.key} />
      </Card>
    {:else if s.kind === 'cap'}
      <div class="r-note">{s.note}</div>
    {/if}
  {/each}
{/if}
