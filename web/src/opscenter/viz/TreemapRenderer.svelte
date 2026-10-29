<script lang="ts">
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
  import { formatMetric } from './format';
  import { TREEMAP_PROVIDERS, defaultQuotaWindow, treemapModelsPlan, treemapProjectsPlan, type DrillTarget } from './plan';
  import { planQuery } from './plan-query.svelte';
  import { treemapDepth, treemapTree, type ProviderModels, type RankRow, type TreeNode } from './shape';
  import { VIZ_SPECS } from './specs';
  import { watchVisible } from './visible';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let node: HTMLDivElement;
  let probe: HTMLSpanElement;
  let open: OpenChart | null = null;
  let visible = $state(false);
  const preset = $derived(config.range.preset ?? VIZ_SPECS.treemap.preset);
  const measure = $derived(config.options?.measure === 'cost' ? 'cost' : 'tokens');
  const context = $derived({ now: analytics.tickAt, timezone: analytics.timezone, filters: analytics.filters, quotaWindow: defaultQuotaWindow(analytics.dimensions) });

  const models = planQuery(() => ({ on: config.enabled, items: treemapModelsPlan(config, context) }), () => visible);
  const rankings = $derived(TREEMAP_PROVIDERS.map((provider, at): { provider: string; rows: RankRow[]; unit: string } => {
    const item = models.outcomes?.[at];
    return { provider, rows: item?.ok ? item.result.ranking ?? [] : [], unit: item?.ok ? item.result.unit : '' };
  }));
  const targets = $derived(rankings.flatMap((entry): DrillTarget[] => entry.rows.filter((row) => row.filter_value && (row.value ?? 0) > 0).map((row) => ({ provider: entry.provider, model: row.filter_value as string }))));
  const projects = planQuery(() => ({ on: config.enabled && targets.length > 0, items: treemapProjectsPlan(config, context, targets) }), () => visible);

  const unit = $derived(rankings.find((entry) => entry.unit)?.unit ?? '');
  const tree = $derived.by((): TreeNode[] => {
    if (!models.outcomes) return [];
    const input: ProviderModels[] = rankings.map((entry) => ({ provider: entry.provider, models: entry.rows, projects: {} }));
    targets.forEach((target, at) => {
      const item = projects.outcomes?.[at];
      if (item?.ok) input.find((entry) => entry.provider === target.provider)!.projects[target.model] = item.result.ranking ?? [];
    });
    return treemapTree(input, t('viz.other'));
  });
  const failed = $derived([...(models.outcomes ?? []), ...(projects.outcomes ?? [])].find((item) => !item.ok));
  const message = $derived(models.failure || projects.failure || (failed && !failed.ok ? failed.error.message : ''));

  function drawable(color: (css: string, fallback: string) => string): unknown[] {
    return treemapDepth(tree, tier === 'tile' ? 1 : tier === 'panel' ? 2 : 3).map((provider, p) => {
      const base = `var(--oc-series-${p % 8 + 1})`;
      const shade = (share: number): string => color(`color-mix(in oklab, ${base} ${share}%, var(--oc-ground-panel))`, '#888');
      return { ...provider, itemStyle: { color: shade(80) }, children: provider.children?.map((model, m) => ({ ...model, itemStyle: { color: shade([80, 62, 46][m % 3] as number) } })) };
    });
  }

  function draw(): void {
    if (!open) return;
    const color = tokenColors(node, probe);
    const text = color('var(--oc-text-primary)', '#fff');
    const ground = color('var(--oc-ground-panel)', '#000');
    const fontFamily = getComputedStyle(node).getPropertyValue('--font-mono').trim() || 'monospace';
    open.chart.setOption({
      animation: false,
      backgroundColor: 'transparent',
      textStyle: { fontFamily },
      tooltip: { confine: true, backgroundColor: color('var(--oc-ground-raised)', '#10232b'), borderColor: color('var(--oc-line-rule)', '#42616a'), textStyle: { color: text, fontSize: 12 },
        formatter: (info: { treePathInfo: { name: string }[]; value: number }) => `${info.treePathInfo.slice(1).map((step) => step.name).join(' / ')}: ${formatMetric(info.value, unit).text}` },
      series: [{
        type: 'treemap', animation: false, data: drawable(color), left: 0, right: 0, top: 0, bottom: 0, roam: false, nodeClick: false, breadcrumb: { show: false },
        squareRatio: 1, visibleMin: 1,
        label: { show: true, color: text, fontSize: 10, overflow: 'truncate', formatter: '{b}' },
        upperLabel: { show: tier !== 'tile', height: 16, color: text, fontSize: 10 },
        itemStyle: { borderColor: ground, borderWidth: 1, gapWidth: 1 },
        levels: [{ itemStyle: { borderWidth: 0, gapWidth: 2 } }, { itemStyle: { gapWidth: 1 } }, { itemStyle: { gapWidth: 1 } }],
      }],
    }, true);
  }

  onMount(() => {
    const stop = watchVisible(root, (value) => { visible = value; });
    open = openChart(node, draw);
    draw();
    return () => { stop(); open?.dispose(); open = null; };
  });

  $effect(() => { void tree; void tier; void unit; draw(); });
  const empty = $derived(tree.length === 0 && models.outcomes !== null && !message);
</script>

<section bind:this={root} class="viz-tree viz-tree--{tier}" class:viz-tree--editing={layoutEditor.active} class:viz-tree--off={!config.enabled} aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-tree__note">{t('analytics.chart_disabled')}</p>
  {/if}
  <header class="viz-tree__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t(`analytics.preset_${preset}`)} · {t(`viz.measure_${measure}`)}</span>{/if}</header>
  {#if message}<p class="viz-tree__note" role="alert">{t('viz.item_failed', { message })}</p>{/if}
  {#if empty}<EmptyState line={emptyLine(measure)} />{/if}
  <div bind:this={node} class="viz-tree__canvas" role="img" aria-label={t('viz.treemap_label', { title: config.title })}></div>
  <span bind:this={probe} hidden></span>
  <VizSettings {config} metric={false}>
    <label>{t('viz.measure')} <select value={measure} onchange={(event) => { changeAnalyticsConfig({ ...config, options: { ...config.options, measure: event.currentTarget.value } }); }}>
      <option value="tokens">{t('viz.measure_tokens')}</option><option value="cost">{t('viz.measure_cost')}</option>
    </select></label>
  </VizSettings>
</section>

<style>
  @layer components {
    .viz-tree { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-tree--editing { overflow: auto; }

    .viz-tree--off .viz-tree__head, .viz-tree--off .viz-tree__canvas { display: none; }

    .viz-tree__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-tree__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-tree__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-tree__canvas { flex: 1; min-height: 60px; margin-top: var(--oc-space-1); }

    .viz-tree__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
