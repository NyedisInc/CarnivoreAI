<script lang="ts">
  import ChartFrame from '../../lib/base/ChartFrame.svelte';
  import NumberField from '../../lib/base/NumberField.svelte';
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import SparkLine from './SparkLine.svelte';
  import VizSettings from './VizSettings.svelte';
  import { analytics, chartTick } from '../cells/analytics/state.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import { layoutEditor, changeAnalyticsConfig } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { formatMetric } from './format';
  import { wholeItems } from './whole-items';
  import { defaultQuotaWindow, leaderboardPlan, leaderboardTopN } from './plan';
  import { planQuery } from './plan-query.svelte';
  import { VIZ_SPECS } from './specs';
  import { leaderboardRows } from './shape';
  import { bucketMsOf, filledValue, observationOf, zeroFills } from '../cells/analytics/gap-fill';
  import { watchVisible } from './visible';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root = $state<HTMLElement | undefined>();
  let visible = $state(false);
  const topN = $derived(leaderboardTopN(config));
  const preset = $derived(config.range.preset ?? VIZ_SPECS.leaderboard.preset);
  const read = planQuery(
    () => ({ on: config.enabled, items: leaderboardPlan(config, { now: chartTick(config), timezone: analytics.timezone, filters: analytics.filters, quotaWindow: defaultQuotaWindow(analytics.dimensions) }) }),
    () => visible,
  );
  onMount(() => (root ? watchVisible(root, (value) => { visible = value; }) : undefined));

  const ranked = $derived(read.outcomes?.[0]?.ok ? read.outcomes[0].result : null);
  const trend = $derived(read.outcomes?.[1]?.ok ? read.outcomes[1].result : null);
  const failed = $derived(read.outcomes?.find((item) => !item.ok));
  const message = $derived(read.failure || (failed && !failed.ok ? failed.error.message : ''));
  const rows = $derived.by(() => {
    const series = config.series.find((item) => item.visible !== false);
    const fill = zeroFills(series?.metric ?? '', series?.transform);
    const now = Date.now();
    const seen = observationOf(analytics.coverage, now);
    return leaderboardRows(ranked?.ranking, trend, topN, (point, points) => filledValue(point.value, point.time, fill, now, seen, bucketMsOf(points)));
  });
  const unit = $derived(ranked?.unit ?? '');
  const total = $derived(rows.reduce((sum, row) => sum + (row.value ?? 0), 0));
</script>
<ChartFrame bind:element={root} size={tier} label={config.title} class="viz-board viz-board--{tier}{layoutEditor.active ? ' viz-board--editing' : ''}">
  {#if !config.enabled}
    <p class="viz-board__note">{t('analytics.chart_disabled')}</p>
  {:else}
    {#if !framing.on || tier !== 'tile'}
      <header class="oc-chart-frame__head viz-board__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t(`analytics.preset_${preset}`)}</span>{/if}</header>
    {/if}
    {#if message}<p class="viz-board__note" role="alert">{t('viz.item_failed', { message })}</p>{/if}
    {#if rows.length === 0 && !message}
      {#if ranked}<div class="oc-chart-frame__empty"><EmptyState line={emptyLine('ranking')} /></div>{/if}
    {:else}
      <div class="viz-board__room" use:wholeItems={{ enabled: !layoutEditor.active }}>
        <ol class="oc-chart-frame__list viz-board__rows">
          {#each rows as row, at (row.key)}
            <li class="viz-board__row">
              <span class="viz-board__rank">{at + 1}</span>
              <span class="viz-board__name" title={row.hint}>{row.label}</span>
              {#if tier !== 'tile'}
                <span class="oc-gauge viz-board__bar" data-scale="2" aria-hidden="true"><span class="oc-gauge__bar"><span class="oc-gauge__fill" style="width:{(row.share * 100).toFixed(1)}%"></span></span></span>
              {/if}
              <span class="viz-board__value">{formatMetric(row.value, unit).text}</span>
              {#if tier === 'full'}
                <span class="viz-board__share">{total > 0 && row.value !== null ? t('viz.percent', { value: (row.value / total * 100).toFixed(0) }) : ''}</span>
                <span class="viz-board__spark"><SparkLine points={row.spark} /></span>
              {/if}
            </li>
          {/each}
        </ol>
      </div>
    {/if}
  {/if}
  <VizSettings {config} group tripwire>
    <NumberField label={t('viz.top_n')} min={1} max={10} stepper value={topN}
      onchange={(next) => { changeAnalyticsConfig({ ...config, options: { ...config.options, top_n: Math.min(10, Math.max(1, Math.floor(next ?? topN))) } }); }} />
  </VizSettings>
</ChartFrame>

<style>
  @layer components {
    :global(.viz-board) { font-family: var(--font-mono); }

    :global(.viz-board--editing) { overflow: auto; }

    .viz-board__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-board__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-board__room { position: relative; flex: 1 1 0; min-height: 0; overflow: hidden; }

    :global(.viz-board--editing) .viz-board__room { overflow: auto; }

    .viz-board__rows { gap: 0; margin-bottom: 0; }

    .viz-board__row { align-items: center; gap: var(--oc-space-2); padding: var(--oc-space-1) 0; box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-board__rank { flex: none; width: 2ch; color: var(--oc-text-dim); font-variant-numeric: tabular-nums; text-align: right; }

    .viz-board__name { flex: 1 1 8ch; min-width: 0; overflow: hidden; color: var(--oc-text-secondary); text-overflow: ellipsis; white-space: nowrap; }

    .viz-board__bar { flex: 2 1 6ch; --oc-gauge-h: var(--oc-space-2); }

    .viz-board__value { flex: none; min-width: 6ch; font-variant-numeric: tabular-nums; text-align: right; }

    .viz-board__share { flex: none; min-width: 4ch; color: var(--oc-text-muted); font-variant-numeric: tabular-nums; text-align: right; }

    .viz-board__spark { flex: 1 1 8ch; min-width: 0; height: var(--oc-space-5); }

    .viz-board__note { margin: var(--oc-space-1) var(--oc-widget-inset); color: var(--oc-text-muted); }
  }
</style>
