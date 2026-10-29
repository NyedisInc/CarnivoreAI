<script lang="ts">
  import Select from '../../lib/base/Select.svelte';
  import { measureOptions } from './settings-options';
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import VizSettings from './VizSettings.svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import { changeAnalyticsConfig, layoutEditor } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { openChart, tokenColors, type OpenChart } from './echarts-setup';
  import { flowDepth, flowDrills, flowGraph, flowLevelsPlan, flowLinksPlan } from './flow';
  import { formatMetric } from './format';
  import { defaultQuotaWindow } from './plan';
  import { planQuery } from './plan-query.svelte';
  import type { RankRow } from './shape';
  import { VIZ_SPECS } from './specs';
  import { watchVisible } from './visible';
  import { escapeHtml } from './tooltip-html';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let node: HTMLDivElement;
  let probe: HTMLSpanElement;
  let open: OpenChart | null = null;
  let visible = $state(false);
  const preset = $derived(config.range.preset ?? VIZ_SPECS.flow.preset);
  const measure = $derived(config.options?.measure === 'cost' ? 'cost' : 'tokens');
  const context = $derived({ now: analytics.tickAt, timezone: analytics.timezone, filters: analytics.filters, quotaWindow: defaultQuotaWindow(analytics.dimensions) });

  const levelsRead = planQuery(() => ({ on: config.enabled, items: flowLevelsPlan(config, context) }), () => visible);
  const levels = $derived([0, 1, 2].map((at): RankRow[] => { const item = levelsRead.outcomes?.[at]; return item?.ok ? item.result.ranking ?? [] : []; }));
  const drills = $derived(flowDrills(levels));
  const linksRead = planQuery(() => ({ on: config.enabled && drills.length > 0, items: flowLinksPlan(config, context, drills) }), () => visible);

  const unit = $derived(levelsRead.outcomes?.flatMap((item) => (item.ok ? [item.result.unit] : []))[0] ?? '');
  const graph = $derived(flowDepth(flowGraph(levels, drills, drills.map((_, at) => { const item = linksRead.outcomes?.[at]; return item?.ok ? item.result.ranking ?? [] : null; }), t('viz.other')), tier === 'tile' ? 2 : tier === 'panel' ? 3 : 4));
  const failed = $derived([...(levelsRead.outcomes ?? []), ...(linksRead.outcomes ?? [])].find((item) => !item.ok));
  const message = $derived(levelsRead.failure || linksRead.failure || (failed && !failed.ok ? failed.error.message : ''));

  const FLOW_LABEL_PX = 140;

  const FLOW_LABEL_PAD_PX = 6;
  const FLOW_MARGIN_PX = 4;
  const FLOW_NODE_PX = 8;

  function flowLabelPx(width: number, columns: number): number {
    if (columns < 2) return FLOW_LABEL_PX;
    const fit = (width - 2 * FLOW_MARGIN_PX - (columns - 1) * (FLOW_NODE_PX + FLOW_LABEL_PAD_PX)) / columns;
    return Math.max(48, Math.min(FLOW_LABEL_PX, Math.floor(fit)));
  }

  function draw(): void {
    if (!open) return;
    const labelPx = flowLabelPx(node.clientWidth, new Set(graph.nodes.map((item) => item.level)).size);
    const color = tokenColors(node, probe);
    const text = color('var(--oc-text-primary)', '#fff');
    const names = new Map(graph.nodes.map((item) => [item.id, item.name]));
    const seen = new Map<number, number>();
    const fontFamily = getComputedStyle(node).getPropertyValue('--font-mono').trim() || 'monospace';
    open.chart.setOption({
      animation: !matchMedia('(prefers-reduced-motion: reduce)').matches,
      backgroundColor: 'transparent',
      textStyle: { fontFamily },
      tooltip: { confine: true, backgroundColor: color('var(--oc-ground-raised)', '#10232b'), borderColor: color('var(--oc-line-rule)', '#42616a'), textStyle: { color: text, fontSize: 12 },
        formatter: (info: { dataType: string; name: string; value: number; data: { source?: string; target?: string } }) => info.dataType === 'edge'
          ? `${escapeHtml(names.get(info.data.source ?? ''))} > ${escapeHtml(names.get(info.data.target ?? ''))}: ${formatMetric(info.value, unit).text}`
          : `${escapeHtml(names.get(info.name) ?? info.name)}: ${formatMetric(info.value, unit).text}` },
      series: [{
        type: 'sankey', left: FLOW_MARGIN_PX, right: tier === 'tile' ? FLOW_MARGIN_PX : labelPx + FLOW_MARGIN_PX, top: 4, bottom: 4, nodeWidth: FLOW_NODE_PX, nodeGap: 6, draggable: false, emphasis: { focus: 'adjacency' },
        lineStyle: { color: 'gradient', opacity: 0.4, curveness: 0.5 },
        label: { show: tier !== 'tile', color: text, fontSize: 10, overflow: 'truncate', width: labelPx - FLOW_LABEL_PAD_PX, formatter: (info: { name: string }) => names.get(info.name) ?? info.name },
        data: graph.nodes.map((item) => {
          const at = seen.get(item.level) ?? 0;
          seen.set(item.level, at + 1);
          return { name: item.id, depth: item.level, itemStyle: { color: color(`var(--oc-series-${(item.level * 3 + at) % 8 + 1})`, '#888') } };
        }),
        links: graph.links,
      }],
    }, true);
  }

  onMount(() => {
    const stop = watchVisible(root, (value) => { visible = value; });
    open = openChart(node, draw);
    draw();
    return () => { stop(); open?.dispose(); open = null; };
  });

  $effect(() => { void graph; void tier; void unit; draw(); });
  const empty = $derived(graph.nodes.length === 0 && levelsRead.outcomes !== null && !message && (drills.length === 0 || linksRead.outcomes !== null));
</script>

<section bind:this={root} class="viz-flow viz-flow--{tier}" class:viz-flow--editing={layoutEditor.active} class:viz-flow--off={!config.enabled} aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-flow__note">{t('analytics.chart_disabled')}</p>
  {/if}
  <header class="viz-flow__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t(`analytics.preset_${preset}`)} · {t(`viz.measure_${measure}`)}</span>{/if}</header>
  {#if message}<p class="viz-flow__note" role="alert">{t('viz.item_failed', { message })}</p>{/if}
  {#if empty}<EmptyState line={emptyLine(measure)} />{/if}
  <div bind:this={node} class="viz-flow__canvas" role="img" aria-label={t('flow.label', { title: config.title })} data-flow-nodes={graph.nodes.length} data-flow-links={graph.links.length}></div>
  <span bind:this={probe} hidden></span>
  {#if tier === 'full'}<p class="viz-flow__key">{t('flow.levels')}</p>{/if}
  <VizSettings {config} metric={false}>
    <Select size="sm" label={t('viz.measure')} value={measure} options={measureOptions()} onchange={(event) => { changeAnalyticsConfig({ ...config, options: { ...config.options, measure: event.currentTarget.value } }); }} />
  </VizSettings>
</section>

<style>
  @layer components {
    .viz-flow { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-flow--editing { overflow: auto; }

    .viz-flow--off .viz-flow__head, .viz-flow--off .viz-flow__canvas { display: none; }

    .viz-flow__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-flow__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-flow__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-flow__canvas { flex: 1; min-height: 60px; margin-top: var(--oc-space-1); }

    .viz-flow__key { margin: var(--oc-space-1) 0 0; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-flow__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
