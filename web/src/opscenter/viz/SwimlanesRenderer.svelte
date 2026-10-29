<script lang="ts">
  /* conversation id */
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { axisCounts } from './axis';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import { sessions } from '../api';
  import VizSettings from './VizSettings.svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import { layoutEditor } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { openChart, tokenColors, type OpenChart } from './echarts-setup';
  import { defaultQuotaWindow, swimlanePlan } from './plan';
  import { planQuery } from './plan-query.svelte';
  import { VIZ_SPECS } from './specs';
  import { laneModel, type LaneSeries } from './swimlanes';
  import { watchVisible } from './visible';

  const IDLE_SHARE = 45;

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let node: HTMLDivElement;
  let probe: HTMLSpanElement;
  let open: OpenChart | null = null;
  let visible = $state(false);
  const preset = $derived(config.range.preset ?? VIZ_SPECS.swimlanes.preset);
  const read = planQuery(
    () => ({ on: config.enabled, items: swimlanePlan(config, { now: analytics.tickAt, timezone: analytics.timezone, filters: analytics.filters, quotaWindow: defaultQuotaWindow(analytics.dimensions) }) }),
    () => visible,
  );
  function seriesOf(at: number): LaneSeries[] {
    const item = read.outcomes?.[at];
    return item?.ok ? item.result.series : [];
  }
  function nameOf(conversationId: string): string | null {
    const row = (sessions.data ?? []).find((item) => item.claude_session_uuid === conversationId);
    return row ? (row.label || row.tmux_session || null) : null;
  }
  const lanes = $derived(laneModel(seriesOf(0), seriesOf(1), seriesOf(2), nameOf));
  const blocks = $derived(lanes.reduce((sum, lane) => sum + lane.blocks.length, 0));
  const failed = $derived((read.outcomes ?? []).find((item) => !item.ok));
  const message = $derived(read.failure || (failed && !failed.ok ? failed.error.message : ''));
  const asked = $derived(read.outcomes !== null);

  function draw(): void {
    if (!open) return;
    const color = tokenColors(node, probe);
    const text = color('var(--oc-text-muted)', '#888');
    const fills = {
      working: color('var(--oc-green)', '#5fcf80'),
      waiting: color('var(--oc-yellow)', '#e0c060'),
      idle: color(`color-mix(in oklab, var(--oc-text-muted) ${IDLE_SHARE}%, var(--oc-ground-panel))`, '#444'),
    };
    const subagent = color('var(--oc-cyan)', '#4fc0d0');
    const labels = tier !== 'tile';
    const insets = { left: labels ? 84 : 2, right: 4, top: 4, bottom: labels ? 18 : 2 };
    const data = lanes.flatMap((lane, index) => lane.blocks.map((block) => [index, block.start, block.end, block.state, block.subagents]));
    open.chart.setOption({
      animation: false,
      backgroundColor: 'transparent',
      textStyle: { fontFamily: getComputedStyle(node).getPropertyValue('--font-mono').trim() || 'monospace' },
      tooltip: { confine: true, backgroundColor: color('var(--oc-ground-raised)', '#10232b'), borderColor: color('var(--oc-line-rule)', '#42616a'), textStyle: { color: color('var(--oc-text-primary)', '#fff'), fontSize: 12 },
        formatter: (info: { value: [number, number, number, string, number] }) => `${lanes[info.value[0]]?.label ?? ''} · ${t(`swimlanes.state_${info.value[3]}`)}` },
      grid: insets,
      xAxis: { type: 'time', splitNumber: axisCounts({ width: node.clientWidth, height: node.clientHeight }, insets).time, splitLine: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: color('var(--oc-line-rule)', '#42616a') } }, axisLabel: { show: labels, color: text, fontSize: 10, hideOverlap: true } },
      yAxis: { type: 'category', data: lanes.map((lane) => lane.label), inverse: true, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { show: labels, color: text, fontSize: 10, width: 76, overflow: 'truncate' } },
      series: [{
        type: 'custom', progressive: 0, encode: { x: [1, 2], y: 0 }, data,
        renderItem: (_params: unknown, api: { value: (dim: number) => number | string; coord: (point: [number, number]) => [number, number]; size: (extent: [number, number]) => [number, number] }) => {
          const lane = api.value(0) as number;
          const from = api.coord([api.value(1) as number, lane]);
          const to = api.coord([api.value(2) as number, lane]);
          const band = api.size([0, 1])[1];
          const height = Math.max(2, band * 0.7);
          const width = Math.max(1, to[0] - from[0]);
          const density = api.value(4) as number;
          const children: unknown[] = [{ type: 'rect', shape: { x: from[0], y: from[1] - height / 2, width, height }, style: { fill: fills[api.value(3) as keyof typeof fills] } }];
          if (density > 0) children.push({ type: 'rect', shape: { x: from[0], y: from[1] + height / 2 - Math.max(1, height * 0.3), width, height: Math.max(1, height * 0.3) }, style: { fill: subagent, opacity: 0.35 + 0.65 * density } });
          return { type: 'group', children };
        },
      }],
    }, true);
  }

  onMount(() => {
    const stop = watchVisible(root, (value) => { visible = value; });
    open = openChart(node, draw);
    draw();
    return () => { stop(); open?.dispose(); open = null; };
  });

  $effect(() => { void lanes; void tier; draw(); });
</script>

<section bind:this={root} class="viz-swim viz-swim--{tier}" class:viz-swim--editing={layoutEditor.active} class:viz-swim--off={!config.enabled} aria-label={config.title} data-lanes={lanes.length} data-blocks={blocks}>
  {#if !config.enabled}
    <p class="viz-swim__note">{t('analytics.chart_disabled')}</p>
  {/if}
  <header class="viz-swim__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t(`analytics.preset_${preset}`)}</span>{/if}</header>
  {#if message}<p class="viz-swim__note" role="alert">{t('viz.item_failed', { message })}</p>{/if}
  {#if asked && lanes.length === 0 && !message}<EmptyState line={emptyLine('activity')} />{/if}
  <div bind:this={node} class="viz-swim__canvas" role="img" aria-label={t('swimlanes.label', { title: config.title })}></div>
  <span bind:this={probe} hidden></span>
  {#if tier !== 'tile' && lanes.length}
    <ul class="viz-swim__key">
      <li class="viz-swim__key--working">{t('swimlanes.state_working')}</li>
      <li class="viz-swim__key--waiting">{t('swimlanes.state_waiting')}</li>
      <li class="viz-swim__key--idle">{t('swimlanes.state_idle')}</li>
      <li class="viz-swim__key--subagents">{t('swimlanes.subagents')}</li>
    </ul>
  {/if}
  <VizSettings {config} metric={false} />
</section>

<style>
  @layer components {
    .viz-swim { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-swim--editing { overflow: auto; }

    .viz-swim--off .viz-swim__head, .viz-swim--off .viz-swim__canvas, .viz-swim--off .viz-swim__key { display: none; }

    .viz-swim__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-swim__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-swim__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-swim__canvas { flex: 1; min-height: 60px; margin-top: var(--oc-space-1); }

    .viz-swim__key { display: flex; flex-wrap: wrap; gap: var(--oc-space-1) var(--oc-space-4); margin: var(--oc-space-1) 0 0; padding: var(--oc-space-1) 0 0; list-style: none; box-shadow: 0 -1px 0 var(--oc-line-faint); color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-swim__key li { display: flex; align-items: center; gap: var(--oc-space-1); }

    .viz-swim__key li::before { content: ''; width: var(--oc-space-2); height: var(--oc-space-2); background: var(--_key); }

    .viz-swim__key--working { --_key: var(--oc-green); }

    .viz-swim__key--waiting { --_key: var(--oc-yellow); }

    .viz-swim__key--idle { --_key: color-mix(in oklab, var(--oc-text-muted) 45%, var(--oc-ground-panel)); }

    .viz-swim__key--subagents { --_key: var(--oc-cyan); }

    .viz-swim__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
