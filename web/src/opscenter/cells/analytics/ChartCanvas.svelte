<script lang="ts">
  import { onMount } from 'svelte';
  import { init, use, type EChartsType } from 'echarts/core';
  import { LineChart, BarChart } from 'echarts/charts';
  import { GridComponent, LegendComponent, LegendScrollComponent, TooltipComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent } from 'echarts/components';
  import { CanvasRenderer } from 'echarts/renderers';
  import type { Annotation, ChartConfig, ChartSeries, QueryResult } from './types';
  import { bucketMsOf, filledValue, observationOf, unobservedSpans, zeroFills } from './gap-fill';
  import { formatSi } from '../../viz/format';
  import { axisCounts } from '../../viz/axis';
  import { legendTextWidth } from './legend-fit';
  import ChartLegend from './ChartLegend.svelte';
  import type { LegendItem } from './legend-pages';
  import { analytics } from './state.svelte';
  import { SERIES_COUNT, assignSeriesLooks, mergeLegendSelection, toSrgb, type ColorContext } from './series-colors';

  use([LineChart, BarChart, GridComponent, LegendComponent, LegendScrollComponent, TooltipComponent, DataZoomComponent, MarkLineComponent, MarkAreaComponent, CanvasRenderer]);

  let { config, results, seriesConfigs, annotations = [], thresholds = [], compact = false, onRangeChange, hiddenSeries = [], onHiddenChange, ownLegend = false, lookFor, wrapLegend = false }: { config: ChartConfig; results: QueryResult[]; seriesConfigs: ChartSeries[]; annotations?: Annotation[]; thresholds?: number[]; compact?: boolean; onRangeChange?: (range: { from: string; to: string } | null) => void; hiddenSeries?: string[]; onHiddenChange?: (hidden: string[]) => void; ownLegend?: boolean; lookFor?: (seriesKey: string) => { color: string; dashed?: boolean } | null; wrapLegend?: boolean } = $props();
  let node: HTMLDivElement;
  let chart: EChartsType | null = null;
  let zoomTimer: ReturnType<typeof setTimeout> | null = null;
  let probe: HTMLSpanElement;
  let drawing = false;
  let drawnAxes: { insets: { left: number; right: number; top: number; bottom: number }; legend: { left: number; right: number; icon: number }; key: string } | null = null;

  function axesKey(counts: { value: number; time: number }, legendPx: number): string {
    return `${counts.value}:${counts.time}:${legendPx}`;
  }

  function retickAfterResize(): void {
    if (!node || !drawnAxes) return;
    const counts = axisCounts({ width: node.clientWidth, height: node.clientHeight }, drawnAxes.insets);
    if (axesKey(counts, legendTextWidth(node.clientWidth, drawnAxes.legend.left, drawnAxes.legend.right, drawnAxes.legend.icon)) !== drawnAxes.key) draw();
  }
  let legendSelected: Record<string, boolean> = {};
  let legendItems = $state<LegendItem[]>([]);

  function showSelection(): void { legendItems = legendItems.map((item) => ({ ...item, on: legendSelected[item.name] !== false })); }

  function toggleSeries(name: string): void { chart?.dispatchAction({ type: 'legendToggleSelect', name }); }
  let colorContext: ColorContext | null = null;
  const seriesFallbacks = ['#f28b82', '#f0a35e', '#d9c65f', '#7fd18b', '#5fcfc4', '#6cb0e0', '#a98fe0', '#e58bc0'];

  function flattener(): ColorContext {
    if (!colorContext) colorContext = document.createElement('canvas').getContext('2d', { willReadFrequently: true }) as ColorContext;
    return colorContext;
  }

  function color(name: string, fallback: string): string {
    if (!getComputedStyle(node).getPropertyValue(name).trim()) return fallback;
    return probed(name, fallback);
  }

  function chosenColor(name: string): string {
    const known = getComputedStyle(node).getPropertyValue(name).trim() !== '';
    return color(known ? name : '--oc-text-secondary', '#888');
  }

  function probed(name: string, fallback: string): string {
    probe.style.color = '';
    probe.style.color = `var(${name})`;
    return toSrgb(getComputedStyle(probe).color, flattener(), fallback);
  }

  function axisValue(unit: string): (value: number) => string {
    return (value) => unit.startsWith('est. USD') ? `$${formatSi(value)}` : formatSi(value);
  }

  const COUNT_UNITS = new Set(['events', 'observations']);


  function seriesName(result: QueryResult, queryIndex: number, label: string): string {
    const metric = seriesConfigs[queryIndex]?.label || analytics.catalog.find((entry) => entry.id === result.metric)?.label
      || result.metric.replace(/_nano_usd$/, '').replaceAll('_', ' ');
    if (!label || label.toLowerCase() === 'all') return metric;
    return results.length === 1 ? label : `${metric} · ${label}`;
  }

  function uniqueNames(raw: string[]): string[] {
    const taken = new Set(raw);
    const seenCount = new Map<string, number>();
    return raw.map((name) => {
      const n = (seenCount.get(name) ?? 0) + 1;
      seenCount.set(name, n);
      if (n === 1) return name;
      let k = n;
      while (taken.has(`${name} (${k})`)) k += 1;
      taken.add(`${name} (${k})`);
      return `${name} (${k})`;
    });
  }

  function markLines(queryIndex: number, itemIndex: number) {
    const marks = !compact && annotations.length && queryIndex === 0 ? annotations.map((event) => ({ name: event.label, xAxis: event.occurred_at * 1000, lineStyle: { type: 'dashed' as const, color: color('--oc-orange', '#f2a261') } })) : [];
    const limits = queryIndex === 0 && itemIndex === 0 ? thresholds.map((value) => ({ yAxis: value, lineStyle: { type: 'dashed' as const, color: color('--oc-coral', '#e78475') } })) : [];
    return marks.length || limits.length ? { silent: true, symbol: 'none', animation: false, label: { show: false }, data: [...marks, ...limits] } : undefined;
  }

  function hatch(): HTMLCanvasElement {
    const tile = document.createElement('canvas');
    tile.width = 6; tile.height = 6;
    const pen = tile.getContext('2d');
    if (pen) {
      pen.strokeStyle = color('--oc-line-rule', '#777');
      pen.globalAlpha = 0.45;
      pen.lineWidth = 1;
      pen.beginPath(); pen.moveTo(0, 6); pen.lineTo(6, 0); pen.stroke();
    }
    return tile;
  }

  function unwatchedBands(result: QueryResult, seen: ReturnType<typeof observationOf>) {
    const points = result.series[0]?.points ?? [];
    const from = Date.parse(result.effective_range?.from ?? String(points[0]?.time ?? ''));
    const to = Math.min(Date.now(), Date.parse(result.effective_range?.to ?? String(points.at(-1)?.time ?? '')));
    const spans = Number.isFinite(from) && Number.isFinite(to) ? unobservedSpans(from, to, seen) : [];
    if (!spans.length) return undefined;
    return { silent: true, animation: false, itemStyle: { color: { image: hatch(), repeat: 'repeat' as const } },
      label: { show: false }, data: spans.map((span) => [{ xAxis: span.from }, { xAxis: span.to }]) };
  }

  function resolveCss(css: string): string {
    if (!node || !css.includes('var(')) return css;
    const probe = document.createElement('span');
    probe.style.color = css;
    node.appendChild(probe);
    const out = getComputedStyle(probe).color;
    probe.remove();
    return out || css;
  }

  function draw(): void {
    if (!chart || !node) return;
    const colors = Array.from({ length: SERIES_COUNT }, (_, i) => color(`--oc-series-${i + 1}`, seriesFallbacks[i] as string));
    const looks = assignSeriesLooks(results.flatMap((result, queryIndex) => result.series.map((item) => `${queryIndex}:${result.metric}:${item.key}`)), colors);
    results.forEach((result, queryIndex) => result.series.forEach((item) => {
      const own = lookFor?.(item.key);
      if (own) looks.set(`${queryIndex}:${result.metric}:${item.key}`, { color: own.color.startsWith('--') ? chosenColor(own.color) : toSrgb(resolveCss(own.color), flattener(), '#888'), dashed: own.dashed === true });
    }));
    const fontFamily = getComputedStyle(node).getPropertyValue('--font-mono').trim() || 'monospace';
    const axisUnit = (unit: string): string => unit.startsWith('nano_usd') ? `est. USD${unit.slice('nano_usd'.length)}` : unit;
    const units = config.display.indexed ? ['index'] : [...new Set(results.map((result) => axisUnit(result.unit)))];
    if (units.length > 2) return;
    const now = Date.now();
    const seen = observationOf(analytics.coverage, now);
    const flatKeys = results.flatMap((result, queryIndex) => result.series.map((item) => `${queryIndex}:${result.metric}:${item.key}`));
    const flatNames = uniqueNames(results.flatMap((result, queryIndex) => result.series.map((item) => seriesName(result, queryIndex, item.label))));
    const nameOf = new Map(flatKeys.map((key, index) => [key, flatNames[index] as string]));
    const series = results.flatMap((result, queryIndex) => result.series.map((item, itemIndex) => ({
      id: `${queryIndex}:${result.metric}:${item.key}:after`,
      name: nameOf.get(`${queryIndex}:${result.metric}:${item.key}`) as string,
      type: config.display.type === 'bar' ? 'bar' : 'line',
      areaStyle: config.display.type === 'area' || (compact && config.display.type === 'line') ? { opacity: compact ? 0.13 : 0.12 } : undefined,
      stack: config.display.stacked ? 'total' : undefined,
      smooth: false,
      showSymbol: false,
      yAxisIndex: config.display.indexed ? 0 : config.display.axes?.[result.metric] === 'right' && units.length > 1 ? 1 : Math.max(0, units.indexOf(axisUnit(result.unit))),
      data: item.points.map((point) => {
        const first = item.points.find((entry) => entry.value !== null && entry.value !== 0)?.value;
        const raw = filledValue(point.value, point.time, zeroFills(result.metric, seriesConfigs[queryIndex]?.transform), now, seen, bucketMsOf(item.points));
        const value = raw === null ? null : config.display.indexed && first ? raw / first * 100 : result.unit.startsWith('nano_usd') ? raw / 1_000_000_000 : raw;
        return [point.time, value];
      }),
      itemStyle: { color: looks.get(`${queryIndex}:${result.metric}:${item.key}`)?.color },
      lineStyle: { width: compact ? 2 : 1.8, type: looks.get(`${queryIndex}:${result.metric}:${item.key}`)?.dashed ? 'dashed' as const : 'solid' as const,
        color: looks.get(`${queryIndex}:${result.metric}:${item.key}`)?.color },
      connectNulls: false,
      markLine: markLines(queryIndex, itemIndex),
      markArea: queryIndex === 0 && itemIndex === 0 ? unwatchedBands(result, seen) : undefined,
    })));
    const beforeSeries = results.flatMap((result, queryIndex) => {
      if (!result.comparison?.series?.length || !result.series.length) return [];
      const offset = new Date(result.effective_range?.from ?? result.series[0]?.points[0]?.time ?? 0).getTime()
        - new Date(result.comparison.range.from).getTime();
      return result.comparison.series.map((item) => ({
        id: `${queryIndex}:${result.metric}:${item.key}:before`,
        name: `${nameOf.get(`${queryIndex}:${result.metric}:${item.key}`) ?? seriesName(result, queryIndex, item.label)} · before`, type: 'line' as const,
        showSymbol: false, lineStyle: { type: 'dashed' as const, width: 1.5, color: looks.get(`${queryIndex}:${result.metric}:${item.key}`)?.color },
        itemStyle: { color: looks.get(`${queryIndex}:${result.metric}:${item.key}`)?.color },
        yAxisIndex: config.display.indexed ? 0 : config.display.axes?.[result.metric] === 'right' && units.length > 1 ? 1 : Math.max(0, units.indexOf(axisUnit(result.unit))),
        data: item.points.map((point) => ({ ...point, value: filledValue(point.value, new Date(point.time).getTime(),
          zeroFills(result.metric, seriesConfigs[queryIndex]?.transform), now - offset, seen, bucketMsOf(item.points)) })).map((point) => [new Date(point.time).getTime() + offset,
          point.value === null ? null : config.display.indexed
            ? (item.points.find((entry) => entry.value !== null && entry.value !== 0)?.value ?? 0)
              ? point.value / (item.points.find((entry) => entry.value !== null && entry.value !== 0)?.value ?? 1) * 100 : null
            : result.unit.startsWith('nano_usd') ? point.value / 1_000_000_000 : point.value]),
      }));
    });
    const names = [...series, ...beforeSeries].map((entry) => entry.name);
    const legendShown = !ownLegend && config.display.legend !== false && (!compact || names.length > 1);
    legendSelected = mergeLegendSelection(legendSelected, names);
    for (const name of names) if (hiddenSeries.includes(name)) legendSelected[name] = false;
    legendItems = compact && legendShown ? [...series, ...beforeSeries].map((entry) => ({ id: entry.id, name: entry.name, color: String(entry.itemStyle.color ?? ''), on: legendSelected[entry.name] !== false })) : [];
    const legendLeft = compact ? 0 : 84;
    const legendRight = 14;
    const legendIcon = compact ? 10 : 25;
    const insets = { left: compact ? 43 : 56, right: units.length > 1 ? 54 : 14, top: compact ? 12 : 32, bottom: compact ? 28 : 42 };
    const counts = axisCounts({ width: node.clientWidth, height: node.clientHeight }, insets);
    drawnAxes = { insets, legend: { left: legendLeft, right: legendRight, icon: legendIcon }, key: axesKey(counts, legendTextWidth(node.clientWidth, legendLeft, legendRight, legendIcon)) };
    drawing = true;
    chart.setOption({
      animation: !matchMedia('(prefers-reduced-motion: reduce)').matches,
      backgroundColor: 'transparent',
      textStyle: { color: color('--oc-text-secondary', '#aaa'), fontFamily },
      color: colors,
      grid: { ...insets, containLabel: false },
      tooltip: { trigger: 'axis', confine: true, backgroundColor: color('--oc-ground-raised', '#10232b'), borderColor: color('--oc-line-rule', '#42616a'), textStyle: { color: color('--oc-text-primary', '#fff'), fontSize: 12 },
        valueFormatter: (value: unknown) => { const point = Array.isArray(value) ? value[1] : value; return typeof point === 'number' ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(point) : 'unknown'; } },
      legend: { type: 'scroll', left: legendLeft, right: legendRight, show: legendShown && !compact, selectedMode: true, selected: legendSelected, top: 0,
        itemWidth: legendIcon, itemHeight: compact ? 6 : 14, textStyle: { color: color('--oc-text-secondary', '#aaa'), fontSize: compact ? 10 : 12,
          width: legendTextWidth(node.clientWidth, legendLeft, legendRight, legendIcon), overflow: 'truncate' as const, ellipsis: '\u2026' }, pageTextStyle: { color: color('--oc-text-secondary', '#aaa') },
        pageIconColor: color('--oc-text-secondary', '#aaa'), pageIconInactiveColor: color('--oc-text-dim', '#666'),
        inactiveColor: color('--oc-text-dim', '#666'), inactiveBorderColor: color('--oc-text-dim', '#666') },
      xAxis: { type: 'time', axisTick: { show: false }, axisLine: { lineStyle: { color: color('--oc-line-rule', '#777') } },
        splitNumber: counts.time, axisLabel: { color: color('--oc-text-muted', '#888'), fontSize: 10, hideOverlap: true, margin: 9 } },
      yAxis: units.map((unit, index) => ({ type: 'value', name: compact ? '' : unit, position: index ? 'right' : 'left',
        splitNumber: counts.value, ...(COUNT_UNITS.has(unit.split('/')[0] ?? unit) ? { minInterval: 1 } : {}),
        axisLabel: { color: color('--oc-text-muted', '#888'), fontSize: 10, hideOverlap: true, formatter: axisValue(unit) },
        splitLine: { lineStyle: { color: color('--oc-line-faint', '#333'), opacity: 0.55 } } })),
      dataZoom: compact ? [] : [{ type: 'inside', zoomOnMouseWheel: 'ctrl', moveOnMouseMove: true },
        ],
      series: [...series, ...beforeSeries],
    }, true);
    chart.resize();
    queueMicrotask(() => { drawing = false; });
  }

  function onZoom(event: { start?: number; end?: number; batch?: { start?: number; end?: number }[] }): void {
    if (drawing || !onRangeChange) return;
    const zoom = event.batch?.[0] ?? event;
    const start = zoom.start ?? 0;
    const end = zoom.end ?? 100;
    if (zoomTimer) clearTimeout(zoomTimer);
    zoomTimer = setTimeout(() => {
      if (start <= 0 && end >= 100) { onRangeChange(null); return; }
      const source = results[0]?.effective_range;
      if (!source) return;
      const from = new Date(source.from).getTime();
      const to = new Date(source.to).getTime();
      if (to <= from) return;
      onRangeChange({ from: new Date(from + (to - from) * start / 100).toISOString(),
        to: new Date(from + (to - from) * end / 100).toISOString() });
    }, 250);
  }

  onMount(() => {
    const observer = new ResizeObserver(() => { chart?.resize(); retickAfterResize(); });
    observer.observe(node);
    const theme = new MutationObserver(draw);
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });
    chart = init(node, undefined, { renderer: 'canvas' });
    chart.on('legendselectchanged', (event: unknown) => {
      legendSelected = { ...(event as { selected: Record<string, boolean> }).selected };
      showSelection();
      const absent = hiddenSeries.filter((name) => !(name in legendSelected));
      onHiddenChange?.([...absent, ...Object.keys(legendSelected).filter((name) => legendSelected[name] === false)].slice(0, 32));
    });
    chart.on('datazoom', (event: unknown) => onZoom(event as Parameters<typeof onZoom>[0]));
    draw();
    return () => { if (zoomTimer) clearTimeout(zoomTimer); observer.disconnect(); theme.disconnect(); chart?.dispose(); chart = null; };
  });

  let shownHidden = '';
  $effect(() => {
    const key = JSON.stringify(hiddenSeries);
    if (key === shownHidden) return;
    shownHidden = key;
    legendSelected = Object.fromEntries(Object.keys(legendSelected).map((name) => [name, !hiddenSeries.includes(name)]));
  });

  $effect(() => { void config; void results; void seriesConfigs; void annotations; void thresholds; void compact; draw(); });

  export function resetZoom(): void { chart?.dispatchAction({ type: 'dataZoom', start: 0, end: 100 }); }
</script>

<div class="analytics-canvas-box" class:analytics-canvas-box--compact={compact}>
  {#if legendItems.length}<ChartLegend items={legendItems} onToggle={toggleSeries} wrap={wrapLegend} />{/if}
  <div bind:this={node} class="analytics-canvas" role="img" aria-label={config.title}></div>
</div>
<span bind:this={probe} hidden></span>

<style>
  @layer components {
    .analytics-canvas-box { display: flex; flex-direction: column; width: 100%; min-height: 100px; height: 100%; }

    .analytics-canvas-box--compact { min-height: 70px; }

    .analytics-canvas { flex: 1 1 0; width: 100%; min-height: 0; touch-action: pan-y; }
  }
</style>
