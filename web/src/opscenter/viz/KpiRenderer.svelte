<script lang="ts">
  import { onMount } from 'svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import EmptyState from './EmptyState.svelte';
  import SparkLine from './SparkLine.svelte';
  import Checkbox from '../../lib/base/Checkbox.svelte';
  import Field from '../../lib/base/Field.svelte';
  import Select from '../../lib/base/Select.svelte';
  import StatTile from '../../lib/base/StatTile.svelte';
  import TripwireEditor from './TripwireEditor.svelte';
  import { analytics, chartTick } from '../cells/analytics/state.svelte';
  import type { ChartConfig, RangePreset, Viz } from '../cells/analytics/types';
  import { changeAnalyticsConfig } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { describeDelta, formatMetric } from './format';
  import { emptyLine, emptyTopic, isBlank } from './empty';
  import { defaultQuotaWindow, kpiPlan } from './plan';
  import { planQuery } from './plan-query.svelte';
  import { VIZ_SPECS, vizOf } from './specs';
  import { metricOptions, rangeOptions, vizKindOptions } from './settings-options';
  import type { Tier } from './density';
  import { watchVisible } from './visible';
  import { declareSettingsPanel } from '../widgets/chrome/settings-panels.svelte';
  import { bucketMsOf, filledValue, observationOf, zeroFills } from '../cells/analytics/gap-fill';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root = $state<HTMLElement | undefined>();
  let visible = $state(false);

  const series = $derived(config.series.find((item) => item.visible !== false));
  const compare = $derived((config.options?.compare_prior ?? VIZ_SPECS.kpi.options.compare_prior) !== false);
  const preset = $derived(config.range.preset ?? VIZ_SPECS.kpi.preset);
  const now = $derived(chartTick(config));
  const read = planQuery(
    () => ({ on: config.enabled, items: kpiPlan(config, { now, timezone: analytics.timezone, filters: analytics.filters, quotaWindow: defaultQuotaWindow(analytics.dimensions) }) }),
    () => visible,
  );
  const outcome = $derived(read.outcomes?.[0] ?? null);
  const failure = $derived(read.failure);

  onMount(() => (root ? watchVisible(root, (value) => { visible = value; }) : undefined));

  const result = $derived(outcome?.ok ? outcome.result : null);
  const message = $derived(failure || (outcome && !outcome.ok ? outcome.error.message : ''));
  const value = $derived(typeof result?.summary?.value === 'number' ? result.summary.value : null);
  const prior = $derived(typeof result?.comparison?.summary?.value === 'number' ? result.comparison.summary.value : null);
  const shown = $derived(formatMetric(value, result?.unit ?? ''));
  const delta = $derived(describeDelta(value, prior));
  const points = $derived.by(() => {
    const fill = zeroFills(series?.metric ?? '', series?.transform);
    const now = Date.now();
    const seen = observationOf(analytics.coverage, now);
    const list = result?.series[0]?.points ?? [];
    return list.map((point) => filledValue(point.value, point.time, fill, now, seen, bucketMsOf(list)));
  });
  const known = $derived(points.filter((point): point is number => point !== null));
  const peak = $derived(known.length ? Math.max(...known) : null);
  const average = $derived(known.length ? known.reduce((sum, point) => sum + point, 0) / known.length : null);
  const empty = $derived(result !== null && !message && isBlank(value) && known.every((point) => point === 0));
  const label = $derived(series?.label || analytics.catalog.find((metric) => metric.id === series?.metric)?.label || config.title);

  function edit(next: Partial<ChartConfig>): void {
    changeAnalyticsConfig({ ...config, ...next });
  }

  $effect(() => declareSettingsPanel(`analytics:${config.id}`, panel));
</script>

<StatTile
  bind:element={root}
  framed={false}
  label={framing.on || !config.enabled ? '' : config.title}
  ariaLabel={config.title}
  meta={config.enabled && tier !== 'tile' ? t(`analytics.preset_${preset}`) : ''}
  figure={shown.text}
  unit={shown.unit}
  figureLabel={`${label}: ${shown.text} ${shown.unit}`.trim()}
  size="regular"
  mode={tier === 'tile' ? 'flat' : 'graph'}
  display={tier !== 'tile'}
  delta={compare ? delta.text : ''}
  deltaNote={delta.direction !== 'none' && tier !== 'tile' ? t('viz.prior_label') : ''}
  deltaTone={delta.direction}
  notice={message ? t('viz.item_failed', { message }) : ''}
  empty={!config.enabled || empty || !(result || message) ? blank : undefined}
  spark={sparkline}
  foot={tier !== 'tile' ? readouts : undefined}
/>

{#snippet blank()}
  {#if !config.enabled}
    <p class="viz-kpi__note">{t('analytics.chart_disabled')}</p>
  {:else if empty}
    <EmptyState line={emptyLine(emptyTopic(series?.metric))} />
  {/if}
{/snippet}

{#snippet sparkline()}<SparkLine {points} />{/snippet}

{#snippet readouts()}
  <dl class="viz-kpi__readouts">
    <div><dt>{t('viz.peak')}</dt><dd>{formatMetric(peak, result?.unit ?? '').text}</dd></div>
    <div><dt>{t('viz.average')}</dt><dd>{formatMetric(average, result?.unit ?? '').text}</dd></div>
    {#if tier === 'full'}
      <div><dt>{t('viz.prior_value')}</dt><dd>{formatMetric(prior, result?.unit ?? '').text}</dd></div>
      {#if typeof result?.summary?.samples === 'number'}<div><dt>{t('viz.samples')}</dt><dd>{result.summary.samples}</dd></div>{/if}
    {/if}
  </dl>
{/snippet}


{#snippet panel()}
  <div class="viz-kpi__edit" data-instance-settings="" aria-label={t('analytics.chart_settings')}>
    <Field label={t('analytics.title')} maxlength={80} value={config.title} oninput={(event) => edit({ title: event.currentTarget.value })} />
    <Select size="sm" label={t('viz.kind')} value={vizOf(config)} options={vizKindOptions()} onchange={(event) => edit({ viz: event.currentTarget.value as ChartConfig['viz'], options: { ...VIZ_SPECS[event.currentTarget.value as Viz].options } })} />
    <Select size="sm" label={t('analytics.metric')} value={series?.metric ?? ''} options={metricOptions(analytics.catalog)} onchange={(event) => edit({ series: config.series.map((item) => item === series ? { ...item, metric: event.currentTarget.value, transform: event.currentTarget.value === 'quota_utilization' || event.currentTarget.value.startsWith('average_') ? 'total' : item.transform } : item) })} />
    <Select size="sm" label={t('analytics.range')} value={config.range.preset ?? ''} options={rangeOptions()} onchange={(event) => edit({ range: { ...config.range, preset: (event.currentTarget.value || null) as RangePreset | null, zoom: null } })} />
    <Checkbox label={t('viz.compare_prior')} checked={compare} onchange={(event) => edit({ options: { ...config.options, compare_prior: event.currentTarget.checked } })} />
    <Checkbox label={t('analytics.enabled')} checked={config.enabled} onchange={(event) => edit({ enabled: event.currentTarget.checked })} />
    <TripwireEditor {config} />
  </div>
{/snippet}

<style>
  @layer components {
    .viz-kpi__readouts { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: var(--oc-space-1) var(--oc-space-5); margin: var(--oc-space-2) 0 0; padding-top: var(--oc-space-2); box-shadow: 0 -1px 0 var(--oc-line-rule); }

    .viz-kpi__readouts div { display: flex; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; }

    .viz-kpi__readouts dt { color: var(--oc-text-muted); }

    .viz-kpi__readouts dd { margin: 0; font-variant-numeric: tabular-nums; }

    .viz-kpi__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }

    .viz-kpi__edit { display: flex; align-items: center; flex-wrap: wrap; gap: var(--oc-space-2); color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-kpi__edit label { display: flex; align-items: center; gap: var(--oc-space-1); }

    .viz-kpi__edit select, .viz-kpi__edit input:not([type='checkbox']) { min-height: var(--oc-space-5); padding: 0 var(--oc-space-2); border: 1px solid var(--oc-line-rule); border-radius: var(--oc-radius-sm); background: var(--oc-ground-raised); color: var(--oc-text-primary); font: inherit; }
  }
</style>
