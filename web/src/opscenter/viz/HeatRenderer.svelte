<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine, emptyTopic } from './empty';
  import { onMount } from 'svelte';
  import VizSettings from './VizSettings.svelte';
  import { analytics, chartTick } from '../cells/analytics/state.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import { layoutEditor } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { openChart, tokenColors, type OpenChart } from './echarts-setup';
  import { formatMetric } from './format';
  import { defaultQuotaWindow, heatPlan } from './plan';
  import { planQuery } from './plan-query.svelte';
  import { heatMatrix } from './shape';
  import { VIZ_SPECS } from './specs';
  import { watchVisible } from './visible';

  const RAMP = [10, 24, 40, 58, 78, 100];

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let node: HTMLDivElement;
  let probe: HTMLSpanElement;
  let open: OpenChart | null = null;
  let visible = $state(false);
  const preset = $derived(config.range.preset ?? VIZ_SPECS.heat.preset);
  const read = planQuery(
    () => ({ on: config.enabled, items: heatPlan(config, { now: chartTick(config), timezone: analytics.timezone, filters: analytics.filters, quotaWindow: defaultQuotaWindow(analytics.dimensions) }) }),
    () => visible,
  );
  const outcome = $derived(read.outcomes?.[0] ?? null);
  const result = $derived(outcome?.ok ? outcome.result : null);
  const message = $derived(read.failure || (outcome && !outcome.ok ? outcome.error.message : ''));
  const matrix = $derived(heatMatrix(result?.series[0]?.points ?? []));
  const unit = $derived(result?.unit ?? '');
  const days = Array.from({ length: 7 }, (_, at) => new Intl.DateTimeFormat(undefined, { weekday: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2024, 0, 1 + at))).toLowerCase());
  const hours = Array.from({ length: 24 }, (_, at) => String(at));

  function draw(): void {
    if (!open) return;
    const color = tokenColors(node, probe);
    const text = color('var(--oc-text-muted)', '#888');
    const ramp = RAMP.map((share) => color(`color-mix(in oklab, var(--oc-series-5) ${share}%, var(--oc-ground-panel))`, '#5fcfc4'));
    const max = matrix.max ?? 0;
    const labels = tier !== 'tile';
    open.chart.setOption({
      animation: false,
      backgroundColor: 'transparent',
      textStyle: { fontFamily: getComputedStyle(node).getPropertyValue('--font-mono').trim() || 'monospace' },
      tooltip: { confine: true, backgroundColor: color('var(--oc-ground-raised)', '#10232b'), borderColor: color('var(--oc-line-rule)', '#42616a'), textStyle: { color: color('var(--oc-text-primary)', '#fff'), fontSize: 12 },
        formatter: (info: { value: [number, number, number] }) => `${days[info.value[1]]} ${info.value[0]}:00 · ${formatMetric(info.value[2], unit).text}` },
      grid: { left: labels ? 30 : 2, right: 2, top: 2, bottom: labels ? 18 : 2 },
      xAxis: { type: 'category', data: hours, splitLine: { show: false }, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { show: labels, color: text, fontSize: 10, interval: (at: number) => at % 6 === 0 } },
      yAxis: { type: 'category', data: days, inverse: true, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { show: labels, color: text, fontSize: 10 } },
      series: [{
        type: 'heatmap', progressive: 0,
        data: matrix.cells.filter((cell) => cell.value !== null).map((cell) => ({
          value: [cell.hour, cell.weekday, cell.value],
          itemStyle: { color: ramp[max > 0 ? Math.min(RAMP.length - 1, Math.floor((cell.value as number) / max * RAMP.length)) : 0], borderColor: color('var(--oc-ground-panel)', '#000'), borderWidth: 1 },
        })),
      }],
    }, true);
  }

  onMount(() => {
    const stop = watchVisible(root, (value) => { visible = value; });
    open = openChart(node, draw);
    draw();
    return () => { stop(); open?.dispose(); open = null; };
  });

  $effect(() => { void matrix; void tier; void unit; draw(); });
  const empty = $derived(result !== null && matrix.max === null);
</script>

<section bind:this={root} class="viz-heat viz-heat--{tier}" class:viz-heat--editing={layoutEditor.active} class:viz-heat--off={!config.enabled} aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-heat__note">{t('analytics.chart_disabled')}</p>
  {/if}
  <header class="viz-heat__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t(`analytics.preset_${preset}`)}</span>{/if}</header>
  {#if message}<p class="viz-heat__note" role="alert">{t('viz.item_failed', { message })}</p>{/if}
  {#if empty}<EmptyState line={emptyLine(emptyTopic(config.series[0]?.metric))} />{/if}
  <div bind:this={node} class="viz-heat__canvas" class:viz-heat__canvas--empty={empty} role="img" aria-label={t('viz.heat_label', { title: config.title })}></div>
  <span bind:this={probe} hidden></span>
  <VizSettings {config} />
</section>

<style>
  @layer components {
    .viz-heat { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-heat--editing { overflow: auto; }

    .viz-heat--off .viz-heat__head, .viz-heat--off .viz-heat__canvas { display: none; }

    .viz-heat__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-heat__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-heat__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-heat__canvas { flex: 1; min-height: 60px; margin-top: var(--oc-space-1); }

    .viz-heat__canvas--empty { visibility: hidden; }

    .viz-heat__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
