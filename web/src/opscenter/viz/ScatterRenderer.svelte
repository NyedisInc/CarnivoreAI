<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { axisCounts } from './axis';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import { openSession, sessions } from '../api';
  import VizSettings from './VizSettings.svelte';
  import { authFetch } from '../api/auth.svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import { layoutEditor } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { openChart, tokenColors, type OpenChart } from './echarts-setup';
  import { formatDuration, formatMetric } from './format';
  import { insightRead } from './insight-query.svelte';
  import { liveSessionFor } from './noc';
  import { scatterPath, scatterPoints, type ConversationsPayload } from './scatter';
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
  const preset = $derived(config.range.preset ?? VIZ_SPECS.scatter.preset);
  const read = insightRead<ConversationsPayload>(() => {
    const path = scatterPath(config, { now: analytics.tickAt, timezone: analytics.timezone, filters: analytics.filters });
    return { key: config.enabled ? path : null, fetch: (signal) => authFetch<ConversationsPayload>(path, { signal }) };
  }, () => visible);
  const shaped = $derived(scatterPoints(read.data?.items ?? []));

  const target = (id: string) => liveSessionFor(id, sessions.data);

  function draw(): void {
    if (!open) return;
    const color = tokenColors(node, probe);
    const text = color('var(--oc-text-primary)', '#fff');
    const muted = color('var(--oc-text-muted)', '#999');
    const dot = color('var(--oc-cyan)', '#4cc');
    const live = color('var(--oc-green)', '#4c4');
    const fontFamily = getComputedStyle(node).getPropertyValue('--font-mono').trim() || 'monospace';
    const axes = tier !== 'tile';
    const insets = { left: axes ? 44 : 6, right: axes ? 14 : 6, top: tier === 'full' ? 22 : 8, bottom: axes ? 22 : 6 };
    const counts = axisCounts({ width: node.clientWidth, height: node.clientHeight }, insets);
    const axis = (name: string, format: (value: number) => string, splitNumber: number) => ({
      type: 'log' as const, name: tier === 'full' ? name : '', nameLocation: 'end' as const, nameTextStyle: { color: muted, fontSize: 10 }, show: axes, splitNumber,
      axisLabel: { color: muted, fontSize: 10, hideOverlap: true, formatter: format }, axisLine: { lineStyle: { color: color('var(--oc-line-rule)', '#456') } }, splitLine: { show: false },
    });
    open.chart.setOption({
      animation: false,
      backgroundColor: 'transparent',
      textStyle: { fontFamily },
      grid: insets,
      tooltip: { confine: true, trigger: 'item', backgroundColor: color('var(--oc-ground-raised)', '#10232b'), borderColor: color('var(--oc-line-rule)', '#42616a'), textStyle: { color: text, fontSize: 12 },
        formatter: (info: { data: { value: number[]; project: string; model: string; tokens: number } }) => `${escapeHtml(info.data.project)} / ${escapeHtml(info.data.model)}<br>${formatDuration(info.data.value[0]! * 60)} · ${formatMetric(info.data.value[1]! * 1e9, 'nano_usd').text} · ${formatMetric(info.data.tokens, 'tokens').text}` },
      xAxis: axis(t('scatter.x'), (value) => formatDuration(value * 60), counts.time),
      yAxis: axis(t('scatter.y'), (value) => formatMetric(value * 1e9, 'nano_usd').text, counts.value),
      series: [{
        type: 'scatter', symbolSize: (_value: number[], info: { data: { size: number } }) => info.data.size,
        data: shaped.points.map((point) => ({ value: [point.minutes, point.usd], id: point.id, project: point.project, model: point.model, tokens: point.tokens, size: point.size,
          itemStyle: { color: target(point.id) ? live : dot, opacity: 0.7, cursor: target(point.id) ? 'pointer' : 'default' } })),
      }],
    }, true);
  }

  onMount(() => {
    const stop = watchVisible(root, (value) => { visible = value; });
    open = openChart(node, draw);
    open.chart.on('click', (info) => {
      const id = (info.data as { id?: string } | null)?.id;
      const session = id ? target(id) : null;
      if (session) openSession(session.session.id, session.tmux_session);
    });
    draw();
    return () => { stop(); open?.dispose(); open = null; };
  });

  $effect(() => { void shaped; void tier; void sessions.data; draw(); });
  const empty = $derived(shaped.points.length === 0 && read.data !== null && !read.failure);
</script>

<section bind:this={root} class="viz-scatter viz-scatter--{tier}" class:viz-scatter--editing={layoutEditor.active} class:viz-scatter--off={!config.enabled} aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-scatter__note">{t('analytics.chart_disabled')}</p>
  {/if}
  <header class="viz-scatter__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t(`analytics.preset_${preset}`)}</span>{/if}</header>
  {#if read.failure}<p class="viz-scatter__note" role="alert">{t('viz.item_failed', { message: read.failure })}</p>{/if}
  {#if empty}<EmptyState line={emptyLine('conversations')} />{/if}
  <div bind:this={node} class="viz-scatter__canvas" role="img" aria-label={t('scatter.label', { title: config.title })} data-scatter-points={shaped.points.length}></div>
  <span bind:this={probe} hidden></span>
  {#if tier === 'full' && read.data}
    <p class="viz-scatter__key">{t('scatter.count', { shown: shaped.points.length, total: read.data.total })}{#if shaped.unpriced > 0} · {t('scatter.unpriced', { count: shaped.unpriced })}{/if}{#if read.data.truncated} · {t('scatter.capped')}{/if}</p>
  {/if}
  <VizSettings {config} metric={false} />
</section>

<style>
  @layer components {
    .viz-scatter { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-scatter--editing { overflow: auto; }

    .viz-scatter--off .viz-scatter__head, .viz-scatter--off .viz-scatter__canvas { display: none; }

    .viz-scatter__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-scatter__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-scatter__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-scatter__canvas { flex: 1; min-height: 60px; margin-top: var(--oc-space-1); }

    .viz-scatter__key { margin: var(--oc-space-1) 0 0; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-scatter__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
