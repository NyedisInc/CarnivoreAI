<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const PIPELINE_WIDGET = defineWidget({ id: 'core.pipeline', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import RunChartTable from '../../ui/RunChartTable.svelte';
  import type { ColumnSpec } from '../../engine/types';
  import PipelineStatusPanel from '../../../lib/pipeline-status/PipelineStatusPanel.svelte';
  import { acquireStatus } from '../../../lib/pipeline-status/store.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { clock, startClock } from '../../lib/frozen-clock.svelte';
  import { agoWords, columnsFor, runTimeWords } from '../../lib/run-chart';
  import { compact } from '../../lib/format';
  import { chartRows, OUTCOME_KEYS, PIPELINE_COLUMNS, pluginAreaKey, pluginWords, sizeWords, type ChartRow } from './model';
  import RunQueue from '../../ui/RunQueue.svelte';
  import { pipelineQueue, pipelineRunning } from './activity';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: CellProps = $props();
  const width = $derived(props.width);
  const phone = $derived(props.phone ?? false);
  const limit = $derived(props.limit ?? null);
  const widget = useWidget(PIPELINE_WIDGET, () => props);

  const { status, release } = untrack(() => acquireStatus());
  onDestroy(release);

  $effect(() => startClock());

  const nowS = $derived.by(() => {
    void clock.now;
    return Date.now() / 1000;
  });

  let selected = $state('');
  const shown = $derived((status.data?.recent ?? []).filter((run) => !selected || run.plugin === selected));
  const rows = $derived(chartRows(shown, nowS, (plugin, rebuild) => pluginWords(t, plugin, rebuild), (plugin) => t(pluginAreaKey(plugin)),
    (detail) => t('pipeline.chart.backups_detail', { count: detail.conversations, size: sizeWords(detail.size_bytes) })));
  const running = $derived(pipelineRunning(status.data?.running ?? [], nowS, t));
  const queue = $derived(pipelineQueue(status.data?.queue ?? { items: [], total: 0 }, nowS, t));
  const shownColumns = $derived<ColumnSpec[]>(columnsFor(PIPELINE_COLUMNS, width, phone));

  function outcomeWords(row: ChartRow): string {
    const outcome = t(OUTCOME_KEYS[row.outcome]);
    return row.error ? t('pipeline.chart.outcome_error', { outcome, error: row.error }) : outcome;
  }
</script>

{#snippet rowCell(row: ChartRow, column: ColumnSpec, _index: number)}
  {#if column.key === 'name'}
    <span class="oc-rc-name" data-outcome={row.outcome}>
      <span class="oc-rc-mark" data-mark={row.outcome} title={outcomeWords(row)} aria-hidden="true"></span>
      <span class="oc-rc-name-text">{row.name}</span>
      <span class="oc-visually-hidden" data-outcome-words>{outcomeWords(row)}</span>
    </span>
  {:else if column.key === 'area'}
    <bdi class="oc-rc-area" title={row.detail ?? undefined}>{row.area ?? t('pipeline.chart.machine')}</bdi>
  {:else if column.key === 'runTime'}
    <span class="oc-rc-muted" title={row.runMs === null ? t('pipeline.chart.not_measured_hint') : undefined}>{row.runMs === null ? t('pipeline.chart.not_measured') : runTimeWords(row.runMs)}</span>
  {:else if column.key === 'ago'}
    <span class="oc-rc-muted">{agoWords(row.agoSeconds)}</span>
  {:else if column.key === 'runs'}
    <span class="oc-rc-muted">{row.runs === null ? t('pipeline.chart.not_measured') : compact(row.runs)}</span>
  {/if}
{/snippet}

<WidgetShell {widget}>
<div class="oc-rc" data-pipeline-cell>
  <PipelineStatusPanel compact bind:selected />
  {#if status.data}
    <RunQueue running={running} queue={queue.shown} more={queue.more} queued={status.data.queue.total} />
    {#if rows.length === 0}
      <State inline data-pipeline-chart-empty title={t('pipeline.chart.empty')} />
    {:else}
      <div data-pipeline-chart>
        <RunChartTable columns={shownColumns} {rows} {limit} {phone} cell={rowCell} />
      </div>
    {/if}
  {/if}
</div>
</WidgetShell>
