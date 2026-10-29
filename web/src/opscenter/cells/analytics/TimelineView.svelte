<script lang="ts">
  import { Button, Checkbox, Field, IconButton, Select } from '../../../lib/base';
  import { onDestroy, onMount } from 'svelte';
  import ChartCanvas from './ChartCanvas.svelte';
  import ChartFrame from '../../../lib/base/ChartFrame.svelte';
  import ChartPending from './ChartPending.svelte';
  import { rememberChartTitle } from './chart-titles';
  import { chartFits, plotBoxHeight } from './plot-fit';
  import DetailsModal from './DetailsModal.svelte';
  import EmptyState from '../../viz/EmptyState.svelte';
  import { emptyLine, emptyTopic, isBlank, seriesBlank } from '../../viz/empty';
  import Icon from '../../ui/Icon.svelte';
  import { live, watchLive } from '../../viz/noc-feed.svelte';
  import TripwireEditor from '../../viz/TripwireEditor.svelte';
  import { seriesUnit, thresholdLines } from '../../viz/tripwire-model';
  import { tripwires } from '../../viz/tripwires.svelte';
  import { auth } from '../../api/auth.svelte';
  import { analytics, chartTick } from './state.svelte';
  import { holdWhileRefreshing, planShape } from './swr';
  import { annotations } from './api';
  import { setHidden } from './chart-view';
  import { clockLabel, formatValue, localValue } from './value-format';
  import { cacheHitRate, displayHeadline } from './headline';
  import { costLine } from './cost-extras';
  import { rankedRowPlan } from '../../viz/rank-rows';
  import { wholeItems } from '../../viz/whole-items';
  import { viewport } from '../../engine/viewport.svelte';
  import { windowLabel } from '../../viz/dimension-label';
  import { SERIES_COUNT } from './series-colors';
  import { claimFrameTitle, framedTitle, useFrameHeader, useHeaderGroup } from '../../shell/frame-header.svelte';
  import { describeDelta, formatDuration } from '../../viz/format';
  import { openModal } from '../../../lib/modal';
  import type { Annotation, ChartConfig, ChartSeries, DetailsView, QueryResult, RangePreset, StatsFilters, Viz } from './types';
  import { changeAnalyticsConfig } from '../../layout-editor/editor.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';
  import type { Tier } from '../../viz/density';
  import { baseRange as baseRangeOf, COST_MODELS, DEFAULT_QUOTA_WINDOW, PRESET_MS, timelinePlan, type PlanContext } from '../../viz/plan';
  import { readSnapshot, writeSnapshot } from './snapshot';
  import { runQueries } from '../../viz/query-client';
  import { VIZ_KINDS, VIZ_SPECS, vizOf } from '../../viz/specs';
  import { watchVisible } from '../../viz/visible';
  import { declareSettingsPanel } from '../../widgets/chrome/settings-panels.svelte';
  import { fitRange } from './range-fit';

  let { instance, tier }: { instance: string; tier: Tier } = $props();
  const id = $derived(instance.slice('analytics:'.length));
  const config = $derived(analytics.charts[id]);
  const activeSeries = $derived(config?.series.filter((series) => series.visible !== false) ?? []);
  let expanded = $state(false);
  let slots = $state<(QueryResult | null)[]>([]);
  const results = $derived(slots.filter((item): item is QueryResult => item !== null));
  const first = $derived(slots[0] ?? null);
  let asOf = $state<string | null>(null);
  let refetch = $state(0);
  let headline = $state<QueryResult | null>(null);
  let context = $state<QueryResult[]>([]);
  let markers = $state<Annotation[]>([]);
  let selectedMarker = $state<Annotation | null>(null);
  let comparisonHours = $state(24);
  let loading = $state(false);
  let answered = $state(false);
  let error = $state('');
  let visible = $state(false);
  const zoomRange = $derived(config?.range.zoom ?? null);
  let requestSeq = 0;
  let shownShape: string | null = null;
  let root = $state<HTMLElement | undefined>();
  const FACTS_MIN_HEIGHT_PX = 300;
  let rootHeight = $state(0);
  const roomForFacts = $derived(rootHeight === 0 || rootHeight >= FACTS_MIN_HEIGHT_PX);
  const FACTS_ROW_MIN_WIDTH_PX = 250;
  const FACTS_ROW_MIN_HEIGHT_PX = 72;
  let rootWidth = $state(0);
  const roomForFactsRow = $derived((rootWidth === 0 || rootWidth >= FACTS_ROW_MIN_WIDTH_PX) && (rootHeight === 0 || rootHeight >= FACTS_ROW_MIN_HEIGHT_PX));
  const compactFacts = $derived(tier === 'tile' || !roomForFacts);
  $effect(() => {
    if (!root || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => { rootHeight = root?.clientHeight ?? 0; rootWidth = root?.clientWidth ?? 0; });
    observer.observe(root);
    return () => observer.disconnect();
  });

  let plot = $state<HTMLElement | null>(null);
  let plotHeight = $state<number | null>(null);
  $effect(() => {
    if (!plot) return;
    const node = plot;
    plotHeight = plotBoxHeight(node);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => { plotHeight = plotBoxHeight(node); });
    const card = node.parentElement;
    const watchRows = () => { observer.observe(node); if (card) for (const row of card.children) observer.observe(row); };
    watchRows();
    const rows = card && typeof MutationObserver !== 'undefined' ? new MutationObserver(() => { watchRows(); plotHeight = plotBoxHeight(node); }) : null;
    if (card) { observer.observe(card); rows?.observe(card, { childList: true }); }
    return () => { observer.disconnect(); rows?.disconnect(); plotHeight = null; };
  });

  const now = $derived(chartTick(config));
  const baseRange = $derived(baseRangeOf(config as ChartConfig, now));
  const markerRange = $derived(selectedMarker ? {
    from: new Date(selectedMarker.occurred_at * 1000).toISOString(),
    to: new Date(selectedMarker.occurred_at * 1000 + comparisonHours * 3600_000).toISOString(),
  } : null);
  const range = $derived(zoomRange ?? markerRange ?? baseRange);
  const units = $derived([...new Set(activeSeries.map((series) => {
    const base = analytics.catalog.find((metric) => metric.id === series.metric)?.unit || 'unknown';
    return series.transform === 'rate' ? `${base}/second` : series.transform === 'per_conversation' ? `${base}/conversation` : base;
  }))]);
  const primary = $derived(activeSeries[0]);
  const periodLabel = $derived(zoomRange || selectedMarker || config?.range.mode === 'pinned' || (config?.range.preset && config.range.preset !== '24h') ? t('analytics.selected_period') : t('analytics.past_day'));
  const periodShort = $derived(periodLabel === t('analytics.selected_period') ? t('analytics.selected_period_short') : t('analytics.past_day_short'));
  const cardKind = $derived(primary?.operation === 'ranking' ? 'ranking' : primary?.metric === 'total_tokens' ? 'tokens'
    : primary?.metric === 'estimated_cost_nano_usd' ? 'cost' : primary?.metric === 'working_seconds' ? 'activity'
    : primary?.metric === 'quota_utilization' ? 'quota' : primary?.metric === 'cache_read_tokens' ? 'cache' : 'chart');
  const showFacts = $derived(cardKind === 'tokens' && context.length > 0 && roomForFactsRow);
  const summaryValue = $derived(typeof headline?.summary?.value === 'number' ? headline.summary.value : null);
  const hitRate = $derived(cacheHitRate(summaryValue, contextValue('input_tokens'), contextValue('cache_write_tokens')));
  const headlineValue = $derived(cardKind === 'cache' ? hitRate : summaryValue);
  const change = $derived(primary?.operation === 'comparison' && typeof first?.comparison?.summary?.value === 'number'
    ? describeDelta(summaryValue, first.comparison.summary.value) : null);
  const headlineLabel = $derived(primary?.label || analytics.catalog.find((metric) => metric.id === primary?.metric)?.label || config?.title || '');
  const quotaWindow = $derived(analytics.dimensions.window?.find((item) => item.filter_value === 'five_hour')
    ?? analytics.dimensions.window?.find((item) => item.filter_value));
  const activeQuotaWindow = $derived(primary?.filters?.window || config?.filters.window || analytics.filters.window || quotaWindow?.filter_value || DEFAULT_QUOTA_WINDOW);
  const planContext = $derived<PlanContext>({ now, timezone: analytics.timezone, filters: analytics.filters, quotaWindow: activeQuotaWindow ?? undefined, marker: markerRange, rolling: true });
  const activeQuotaLabel = $derived(analytics.dimensions.window?.find((item) => item.filter_value === activeQuotaWindow)?.label || (activeQuotaWindow ? windowLabel(activeQuotaWindow) : activeQuotaWindow));
  const cardTitle = $derived(config?.title === 'token history' ? t('analytics.tokens_used') : config?.title === 'estimated cost history' ? t('analytics.estimated_cost')
    : primary?.metric === 'quota_utilization' && activeQuotaLabel && config?.title ? `${config.title} · ${activeQuotaLabel}` : config?.title || '');
  const framing = framedTitle();
  const frameHeader = useFrameHeader();
  const rangePlace = useHeaderGroup(() => (config?.enabled ? rangeGroup : null));
  const openPlace = useHeaderGroup(() => (config?.enabled ? openGroup : null));
  $effect(() =>
    frameHeader && config?.enabled
      ? declareWidgetActions(frameHeader.hostId, 'expand', [{ id: 'expand', label: t('analytics.expand'), run: openDetails }])
      : undefined,
  );
  $effect(() => {
    if (!frameHeader) return;
    const mine = cardTitle || null;
    rememberChartTitle(id, mine);
    return claimFrameTitle(frameHeader, mine);
  });
  const thresholds = $derived(primary ? thresholdLines(tripwires.list, id, primary.metric,
    seriesUnit(Object.fromEntries(analytics.catalog.map((entry) => [entry.id, entry.unit ?? ''])), primary), config?.display.indexed === true) : []);
  const ranked = $derived(first?.ranking ?? []);
  const costRanked = $derived(context.find((item) => item.operation === 'ranking')?.ranking ?? []);
  const costPrior = $derived(context.find((item) => item.operation === 'comparison')?.comparison?.summary?.value ?? null);
  let rankRoom = $state<HTMLElement | null>(null);
  let rankRoomPx = $state(0);
  $effect(() => {
    if (!rankRoom || typeof ResizeObserver === 'undefined') return;
    const node = rankRoom;
    const observer = new ResizeObserver(() => { rankRoomPx = node.clientHeight; });
    observer.observe(node);
    return () => observer.disconnect();
  });
  const costSpanMs = $derived(new Date(baseRange.to).getTime() - new Date(baseRange.from).getTime());
  const costExtras = $derived(costLine(summaryValue, costPrior, headline?.unit || '', costSpanMs));
  const numberOnly = $derived(cardKind === 'cost' && !primary?.group_by && (primary?.operation || 'timeline') === 'timeline');
  const unpriced = $derived(headline?.coverage?.unpriced_usage_count ?? 0);
  const costContext = $derived([
    t('analytics.priced_subtotal'),
    headline?.coverage?.priced_token_total ? `${compactCount(headline.coverage.priced_token_total)} ${t('analytics.priced_tokens')}` : '',
    headline?.coverage?.unpriced_token_total ? `${compactCount(headline.coverage.unpriced_token_total)} ${t('analytics.unpriced_tokens')}` : '',
    headline?.coverage?.mixed_price_token_total ? `${compactCount(headline.coverage.mixed_price_token_total)} ${t('analytics.mixed_price_tokens')}` : '',
    unpriced ? `${unpriced} ${t('analytics.unpriced_observations')}` : '',
  ].filter(Boolean).join(' · '));
  const empty = $derived(Boolean(config?.enabled) && ((cardKind === 'quota' && !activeQuotaWindow) || (answered && !error && (
    cardKind === 'ranking' ? ranked.length === 0
      : cardKind === 'quota' ? seriesBlank(results)
        : isBlank(headlineValue) && seriesBlank(results)))));
  const emptyText = $derived(emptyLine(emptyTopic(primary?.metric, cardKind === 'ranking')));
  const conversations = $derived(Number(headline?.summary?.contributing_conversations) || 0);
  $effect(() => watchLive());
  const runningNow = $derived(Number(live.data?.metrics?.running_sessions) || 0);

  const fullestQuota = $derived.by(() => {
    const latest = (first?.series ?? []).map((series) => quotaValue(series.points)).filter((value): value is number => value !== null);
    return latest.length ? Math.max(...latest) : null;
  });

  const headlineText = $derived(cardKind === 'activity' ? duration(headlineValue)
    : cardKind === 'quota' ? displayHeadline(fullestQuota, 'percent')
      : displayHeadline(headlineValue, cardKind === 'cache' ? 'fraction' : headline?.unit || ''));
  const headlineCaption = $derived(cardKind === 'activity' ? t('analytics.working_time') : cardKind === 'quota' ? t('analytics.quota_fullest')
    : cardKind === 'cache' ? t('analytics.cache_hit_caption') : headlineUnit(headline?.unit || ''));

  function headlineUnit(unit: string): string {
    return unit.startsWith('nano_usd') ? `${t('analytics.estimated_usd')}${unit.slice('nano_usd'.length)}` : unit === 'fraction' || unit === 'percent' ? '' : unit;
  }

  function contextValue(metric: string): number | null {
    const value = context.find((result) => result.metric === metric)?.summary?.value;
    return typeof value === 'number' ? value : null;
  }

  function compactCount(value: number | null): string {
    return value === null ? t('analytics.unknown') : displayHeadline(value, 'tokens');
  }

  function duration(value: number | null): string {
    return value === null ? t('analytics.unknown') : formatDuration(value);
  }

  function coverageNote(): string {
    if (!headline) return '';
    if (cardKind === 'cost' && unpriced > 0) return `${unpriced} ${t('analytics.unpriced_observations')}`;
    if (headline.coverage?.unknown_value_rows || headline.coverage?.quality_rows) return t('analytics.partial_data');
    return '';
  }

  function quotaValue(points: QueryResult['series'][number]['points']): number | null {
    return [...points].reverse().find((point) => point.value !== null)?.value ?? null;
  }

  function rankWidth(value: number | null, rows: { value: number | null }[]): number {
    const top = Math.max(0, ...rows.map((item) => item.value ?? 0));
    return typeof value === 'number' && top > 0 ? Math.max(2, value / top * 100) : 0;
  }

  function openDetails(): void {
    if (expanded || !config) return;
    expanded = true;
    const opened = config;
    const view: DetailsView = {
      get id() { return id; },
      get title() { return cardTitle; },
      get period() { return periodLabel; },
      get config() { return config ?? opened; },
      get results() { return results; },
      get markers() { return markers; },
      get activeSeries() { return activeSeries; },
      get units() { return units; },
      get thresholds() { return thresholds; },
      get range() { return range; },
      get baseRange() { return baseRange; },
      get quotaWindow() { return activeQuotaWindow ?? undefined; },
      get selectedMarker() { return selectedMarker; },
      get comparisonHours() { return comparisonHours; },
      get open() { return expanded && Boolean(config); },
      selectMarker(marker) { selectedMarker = marker; },
      setComparisonHours(hours) { comparisonHours = hours; },
      setMarkers(next) { markers = next; },
    };
    void openModal(DetailsModal, { view }).then(closeDetails);
  }

  function closeDetails(): void { expanded = false; selectedMarker = null; }

  onDestroy(() => { expanded = false; });

  const queryKey = $derived.by(() => {
    const plan = timelinePlan(config as ChartConfig, planContext);
    const rolling = plan.bodies.length > 0 && plan.bodies.every((body) => body.rolling);
    return JSON.stringify({ enabled: config?.enabled, plan,
      filters: { ...analytics.filters, ...config?.filters }, tick: rolling ? now : null, from: rolling ? null : range.from, to: rolling ? null : range.to });
  });

  function markerWindow(parsed: { from: string | null; to: string | null }, preset: RangePreset | undefined): { from: string; to: string } {
    if (parsed.from && parsed.to) return { from: parsed.from, to: parsed.to };
    const end = Date.now();
    return { from: new Date(end - PRESET_MS[preset ?? '24h']).toISOString(), to: new Date(end).toISOString() };
  }

  function oldest(times: (string | null)[]): string | null {
    const known = times.filter((time): time is string => time !== null);
    return known.length ? known.reduce((a, b) => (a < b ? a : b)) : null;
  }

  let lastSlots: (QueryResult | null)[] = [];
  let lastHeadline: QueryResult | null = null;
  let lastContext: QueryResult[] = [];
  let lastAsOf: string | null = null;
  let followUps = 0;
  let followTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    void refetch;
    const parsed = JSON.parse(queryKey) as { enabled: boolean; plan: ReturnType<typeof timelinePlan>; filters: Record<string, string | undefined>; from: string | null; to: string | null };
    const plan = parsed.plan;
    if (!parsed.enabled || !visible || plan.bodies.length === 0) {
      if (!parsed.enabled || plan.bodies.length === 0) { slots = []; lastSlots = []; headline = null; context = []; shownShape = null; error = ''; answered = false; asOf = null; }
      return;
    }
    const epoch = ++requestSeq;
    const abort = new AbortController();
    const shape = planShape(plan.bodies, plan.context.map((body) => body.metric));
    if (holdWhileRefreshing(shownShape, shape, false, true)) { slots = []; lastSlots = []; headline = null; lastHeadline = null; context = []; lastContext = []; markers = []; answered = false; asOf = null; lastAsOf = null; shownShape = null; }
    const saved = shownShape === null ? readSnapshot(id, shape) : null;
    if (saved) {
      slots = saved.results; lastSlots = saved.results; headline = lastHeadline = saved.headline; context = lastContext = saved.context;
      answered = true; asOf = lastAsOf = saved.asOf; shownShape = shape;
    }
    loading = true;
    error = '';
    const span = markerWindow(parsed, plan.bodies[0]?.rolling);
    const events = annotations(span.from, span.to, abort.signal, parsed.filters).catch((cause: unknown) => {
      if (abort.signal.aborted) throw cause;
      return [] as Annotation[];
    });
    void Promise.all([runQueries(plan.all, abort.signal), events]).then(([outcomes, found]) => {
      if (epoch !== requestSeq) return;
      const seriesOutcomes = outcomes.slice(0, plan.bodies.length);
      const failed = outcomes.find((item) => !item.ok);
      error = failed && !failed.ok ? failed.error.message : '';
      const own = (at: number): QueryResult | null => { const item = outcomes[at]; return item?.ok ? item.result : null; };
      const next = seriesOutcomes.map((item, at) => (item.ok ? item.result : lastSlots[at] ?? null));
      const nextHeadline = plan.summary ? own(plan.bodies.length) ?? lastHeadline : null;
      const nextContext = plan.context.map((body, at) => own(plan.bodies.length + 1 + at) ?? lastContext.find((item) => item.metric === body.metric && item.operation === body.operation) ?? null)
        .filter((item): item is QueryResult => item !== null);
      const stale = outcomes.flatMap((item) => (item.ok && item.answer?.stale ? [item.answer.as_of] : []));
      const degraded = stale.length > 0 || Boolean(failed);
      lastAsOf = degraded ? oldest([...stale, ...(failed ? [lastAsOf] : [])]) ?? lastAsOf : new Date().toISOString();
      asOf = degraded ? lastAsOf : null;
      slots = lastSlots = next; headline = lastHeadline = nextHeadline; context = lastContext = nextContext;
      markers = found;
      shownShape = shape;
      answered = true;
      if (next.some((item) => item !== null)) writeSnapshot(id, { shape, asOf: lastAsOf ?? new Date().toISOString(), results: next, headline: nextHeadline, context: nextContext });
      if (outcomes.some((item) => item.ok && item.answer?.reason === 'refreshing') && followUps < 3) {
        followUps += 1;
        followTimer = setTimeout(() => { refetch += 1; }, 2000);
      } else followUps = 0;
    }).catch((cause: unknown) => {
      if (!abort.signal.aborted && epoch === requestSeq) { error = cause instanceof Error ? cause.message : t('analytics.query_failed'); }
    }).finally(() => { if (epoch === requestSeq) loading = false; });
    return () => { abort.abort(); if (followTimer !== null) { clearTimeout(followTimer); followTimer = null; } };
  });

  onMount(() => (root ? watchVisible(root, (value) => { visible = value; }) : undefined));

  function edit(next: Partial<ChartConfig>): void {
    if (config) changeAnalyticsConfig({ ...config, ...next });
  }

  function editSeries(index: number, patch: Partial<ChartSeries>): void {
    if (!config) return;
    if (patch.metric === 'quota_utilization' || patch.metric?.startsWith('average_')) patch.transform = 'total';
    if (patch.metric) {
      const groups = analytics.catalog.find((entry) => entry.id === patch.metric)?.group_by ?? [];
      if (config.series[index]?.group_by && !groups.includes(config.series[index].group_by)) patch.group_by = undefined;
    }
    edit({ series: config.series.map((series, at) => at === index ? { ...series, ...patch } : series) });
  }

  function editSeriesFilter(index: number, key: keyof StatsFilters, value: string): void {
    if (!config) return;
    const series = config.series[index];
    if (series) editSeries(index, { filters: { ...series.filters, [key]: value || undefined } });
  }

  function pinTime(side: 'from' | 'to', value: string): void {
    if (!config || config.range.mode !== 'pinned') return;
    const date = new Date(value);
    if (Number.isFinite(date.getTime())) edit({ range: { ...config.range, [side]: date.toISOString() } });
  }

  $effect(() => declareSettingsPanel(instance, panel));

</script>

<ChartFrame bind:element={root} size={tier} busy={loading && results.length > 0} class="analytics-cell analytics-cell--{tier}" label={config?.title || t('opscenter.cell.analytics.title')}>
  {#if !config}
    <ChartPending />
  {:else}
    {#if !config.enabled}<p class="analytics-note">{t('analytics.chart_disabled')}</p>{:else}
    {#if !openPlace.up}{@render openButton('float')}{/if}
    {#if !rangePlace.up}
    <div class="analytics-heading oc-chart-frame__head">
      <div class="analytics-identity">{#if !framing.on}<strong>{cardTitle}</strong>{/if}{@render rangeLabels()}</div>
    </div>
    {/if}
    {#if empty}
    <div class="analytics-empty oc-chart-frame__empty"><EmptyState line={emptyText} /></div>
    {:else if !answered && !error}
    {#if auth.state === 'signed-out'}<p class="analytics-note" role="status">{t('analytics.signed_out')}</p>
    {:else if loading}<p class="analytics-note" role="status">{t('analytics.loading')}</p>{/if}
    {:else}
    {#if cardKind !== 'ranking'}
    <div class="analytics-headline oc-chart-frame__headline" class:analytics-headline--tokens={showFacts} aria-label={`${headlineLabel}: ${headlineText}`}>
      <strong>{headlineText}</strong>
      <span>{headlineCaption}</span>
      {#if showFacts}
      <dl class="analytics-facts oc-chart-frame__facts analytics-facts--tokens analytics-facts--corner">
        <div><dt>{t('analytics.fresh_input')}</dt><dd>{compactCount(contextValue('input_tokens'))}</dd></div>
        <div><dt>{t('analytics.output')}</dt><dd>{compactCount(contextValue('output_tokens'))}</dd></div>
        <div><dt>{t('analytics.cache_write')}</dt><dd>{compactCount(contextValue('cache_write_tokens'))}</dd></div>
        <div><dt>{t('analytics.cache_read')}</dt><dd>{compactCount(contextValue('cache_read_tokens'))}</dd></div>
      </dl>
      {/if}
    </div>
    {/if}
    {#if cardKind === 'ranking'}
      {#if coverageNote()}<p class="analytics-caveat oc-chart-frame__note">{coverageNote()}</p>{/if}
    {:else if change}
      <p class="analytics-change oc-chart-frame__note analytics-change--{change.direction}"><b>{change.text}</b>{#if change.direction !== 'none'} <span>{t('viz.prior_label')}</span>{/if}</p>
    {:else}
      <p class="analytics-caveat oc-chart-frame__note">{coverageNote() || '\u00a0'}</p>
    {/if}
    {#if cardKind === 'tokens' && context.length}
      {#if !compactFacts}
      <div class="analytics-metadata">
      <p class="analytics-context oc-chart-frame__context">
        {#if headlineValue !== null && headlineValue > 0 && contextValue('cache_read_tokens') !== null}
          {displayHeadline((contextValue('cache_read_tokens') ?? 0) / headlineValue, 'fraction')} {t('analytics.cached_share')} ·
        {/if}
        {#if conversations > 0}{conversations} {t('analytics.contributing_conversations')}{/if}
        {#if headlineValue !== null && conversations > 0}
          · {compactCount(headlineValue / conversations)} {t('analytics.per_conversation')}
        {/if}
      </p>
      </div>
      {/if}
    {:else if cardKind === 'cost' && tier !== 'tile' && roomForFacts}
      <div class="analytics-metadata">
      <p class="analytics-context oc-chart-frame__context">{costContext}</p>
      </div>
    {:else if cardKind === 'cache' && context.length && tier !== 'tile' && roomForFacts}
      <dl class="analytics-facts oc-chart-frame__facts">
        <div><dt>{t('analytics.cache_read')}</dt><dd>{compactCount(summaryValue)}</dd></div>
        <div><dt>{t('analytics.fresh_input')}</dt><dd>{compactCount(contextValue('input_tokens'))}</dd></div>
        <div><dt>{t('analytics.cache_write')}</dt><dd>{compactCount(contextValue('cache_write_tokens'))}</dd></div>
      </dl>
    {:else if cardKind === 'activity' && context.length && tier !== 'tile' && roomForFacts}
      <dl class="analytics-facts oc-chart-frame__facts">
        <div><dt>{t('analytics.starts')}</dt><dd>{compactCount(contextValue('starts'))}</dd></div>
        <div><dt>{t('analytics.completions')}</dt><dd>{compactCount(contextValue('completions'))}</dd></div>
        <div><dt>{t('analytics.working_time')}</dt><dd>{duration(headlineValue)}</dd></div>
        <div><dt>{t('analytics.running_time')}</dt><dd>{duration(contextValue('running_seconds'))}</dd></div>
      </dl>
      {#if !isBlank(contextValue('average_working_agents')) || runningNow > 0}
      <p class="analytics-context oc-chart-frame__context">{#if !isBlank(contextValue('average_working_agents'))}{t('analytics.average_working')}: {formatValue(contextValue('average_working_agents'), 'agents')}{/if}
        {#if runningNow > 0}{#if !isBlank(contextValue('average_working_agents'))} · {/if}{t('analytics.live')}: {runningNow} {t('analytics.running')}{#if Number(live.data?.metrics?.working_agents) > 0}, {live.data?.metrics?.working_agents} {t('analytics.working')}{/if}{/if}</p>
      {/if}
      {#if markers.some((marker) => marker.kind === 'rule')}<p class="analytics-context oc-chart-frame__context">{markers.filter((marker) => marker.kind === 'rule').length} {t('analytics.rule_changes')} · {t('analytics.compare_in_details')}</p>{/if}
    {:else if cardKind === 'quota' && tier !== 'tile'}
      <ul class="analytics-quota-legend oc-chart-frame__list" use:wholeItems>
        
        {#each (first?.series ?? []).slice(0, 4) as series, index (series.key)}
          <li><i class="analytics-swatch" style:background={`var(--oc-series-${index % SERIES_COUNT + 1})`} aria-hidden="true"></i><span title={series.label}>{series.label}</span><strong>{formatValue(quotaValue(series.points), 'percent')}</strong></li>
        {/each}
      </ul>
    {:else if cardKind === 'ranking'}
      {#if ranked.length}
        <div bind:this={rankRoom} class="analytics-ranking-room" class:analytics-ranking-room--free={!viewport.wide}>{@render rankList(ranked, first?.unit || '', 4)}</div>
      {/if}
    {/if}
    {#if numberOnly && (costExtras.change || costExtras.average || costRanked.length)}
      <p class="analytics-change oc-chart-frame__note analytics-change--cost analytics-change--{costExtras.change?.direction ?? 'none'}">{#if costExtras.change}<b>{costExtras.change.text}</b>{/if}{#if costExtras.average}<span>{#if costExtras.change}· {/if}{costExtras.average}</span>{/if}</p>
      {#if costRanked.length}<div bind:this={rankRoom} class="analytics-ranking-room" class:analytics-ranking-room--free={!viewport.wide}>{@render rankList(costRanked, headline?.unit || '', COST_MODELS)}</div>{/if}
    {/if}
    {#if error}<p class="analytics-note" role="alert">{error}</p>{/if}
    {#if units.length > 2 && !config.display.indexed}<p class="analytics-note" role="alert">{t('analytics.two_axes')}</p>{/if}
    {#if cardKind !== 'ranking' && !numberOnly && results.some((result) => result.series.length) && (units.length <= 2 || config.display.indexed)}
      <div bind:this={plot} class="analytics-plot oc-chart-frame__plot" class:analytics-plot--yield={cardKind === 'tokens' && compactFacts} class:analytics-plot--dropped={plotHeight !== null && !chartFits(plotHeight)}>
        {#if chartFits(plotHeight)}<ChartCanvas {config} {results} seriesConfigs={activeSeries} compact={tier !== 'full'} ownLegend={cardKind === 'quota' && tier !== 'tile' && tier !== 'full'} annotations={tier === 'full' ? markers : []} {thresholds} hiddenSeries={config.display.hidden_series ?? []} onHiddenChange={tier === 'full' ? (hidden) => setHidden(id, hidden) : undefined} />{/if}
      </div>
    {/if}
    {/if}
    {/if}
  {/if}
</ChartFrame>

{#snippet rankList(rows: NonNullable<QueryResult['ranking']>, unit: string, most: number)}
  {@const plan = rankedRowPlan(viewport.wide ? rankRoomPx : 0, rows.length, most)}
  <ol class="analytics-ranking oc-chart-frame__list" class:analytics-ranking--bare={!plan.bars}>
    {#each rows.slice(0, plan.count) as rank (rank.key)}
      <li><div class="analytics-ranking-row"><span title={rank.label}>{rank.label}</span><strong>{displayHeadline(rank.value, unit)}</strong></div>
        {#if plan.bars}<div class="analytics-ranking-track"><div class="analytics-ranking-fill" style={`width: ${rankWidth(rank.value, rows)}%`}></div></div>{/if}
      </li>
    {/each}
  </ol>
{/snippet}

{#snippet rangeLabels()}
  <span class="analytics-period">{periodLabel}</span><span class="analytics-period analytics-period--short" aria-hidden="true">{periodShort}</span>{#if asOf}<span class="analytics-asof" title={asOf}>{t('analytics.as_of', { time: clockLabel(asOf) })}</span>{/if}
{/snippet}

{#snippet rangeGroup()}
  <span class="analytics-range" use:fitRange={periodLabel}>{@render rangeLabels()}</span>
{/snippet}

{#snippet openButton(look: 'float' | 'quiet')}
  <span class:analytics-open={look === 'float'}>
    <IconButton label={t('analytics.open_details')} variant={look} icon="expand" iconSize={13} data-analytics-open="" aria-haspopup="dialog" aria-expanded={expanded}
      onclick={openDetails} />
  </span>
{/snippet}

{#snippet openGroup()}
  {@render openButton('quiet')}
{/snippet}


{#snippet panel()}
  {#if config}
  <div class="analytics-edit" data-instance-settings="" aria-label={t('analytics.chart_settings')}>
    <label>{t('analytics.title')} <Field maxlength={80} value={config.title} oninput={(event) => edit({ title: event.currentTarget.value })} /></label>
    <label>{t('viz.kind')} <Select size="sm" value={vizOf(config)} onchange={(event) => edit({ viz: event.currentTarget.value as ChartConfig['viz'], options: { ...VIZ_SPECS[event.currentTarget.value as Viz].options } })}>{#snippet children()}
      {#each VIZ_KINDS as kind (kind)}<option value={kind}>{t(`viz.${kind}`)}</option>{/each}
    {/snippet}</Select></label>
    {#each config.series as series, index (index)}
      <Checkbox label={t('analytics.visible')} checked={series.visible !== false} onchange={(event) => editSeries(index, { visible: event.currentTarget.checked })} />
      <label>{t('analytics.series_label')} <Field maxlength={80} value={series.label || ''} oninput={(event) => editSeries(index, { label: event.currentTarget.value || undefined })} /></label>
      <label>{t('analytics.metric')} {index + 1} <Select size="sm" value={series.metric} onchange={(event) => editSeries(index, { metric: event.currentTarget.value })}>{#snippet children()}
        {#each analytics.catalog as metric (metric.id)}<option value={metric.id}>{metric.label || metric.id}</option>{/each}
      {/snippet}</Select></label>
      <label>{t('analytics.transform')} <Select size="sm" value={series.transform || 'total'} disabled={series.metric === 'quota_utilization' || series.metric.startsWith('average_')} onchange={(event) => editSeries(index, { transform: event.currentTarget.value as ChartSeries['transform'] })}>{#snippet children()}
        <option value="total">{t('analytics.total')}</option><option value="rate">{t('analytics.rate')}</option><option value="cumulative">{t('analytics.cumulative')}</option><option value="per_conversation">{t('analytics.per_conversation')}</option>
      {/snippet}</Select></label>
      {#each ['provider', 'project', 'model', 'agent_kind'] as dimension (dimension)}
        <label>{t(`analytics.${dimension}`)} <Select size="sm" value={series.filters?.[dimension as keyof StatsFilters] || ''} onchange={(event) => editSeriesFilter(index, dimension as keyof StatsFilters, event.currentTarget.value)}>{#snippet children()}
          <option value="">{t('analytics.all')}</option>
          {#each analytics.dimensions[dimension] || [] as item (item.key)}{#if item.filter_value}<option value={item.filter_value}>{item.label}</option>{/if}{/each}
        {/snippet}</Select></label>
      {/each}
      <label>{t('analytics.view')} <Select size="sm" value={series.operation || 'timeline'} onchange={(event) => edit({ series: config.series.map((item, at) => at === index ? { ...item, operation: event.currentTarget.value as typeof item.operation } : item) })}>{#snippet children()}
        <option value="timeline">{t('analytics.timeline')}</option><option value="summary">{t('analytics.summary')}</option><option value="ranking">{t('analytics.ranking')}</option><option value="comparison">{t('analytics.before_after')}</option>
      {/snippet}</Select></label>
      <label>{t('analytics.group')} <Select size="sm" value={series.group_by || ''} onchange={(event) => edit({ series: config.series.map((item, at) => at === index ? { ...item, group_by: event.currentTarget.value || undefined } : item) })}>{#snippet children()}
        <option value="">{t('analytics.none')}</option>{#each analytics.catalog.find((metric) => metric.id === series.metric)?.group_by || [] as group (group)}<option value={group}>{group}</option>{/each}
      {/snippet}</Select></label>
      <label>{t('analytics.axis')} <Select size="sm" value={config.display.axes?.[series.metric] || 'left'} onchange={(event) => edit({ display: { ...config.display, axes: { ...config.display.axes, [series.metric]: event.currentTarget.value as 'left' | 'right' } } })}>{#snippet children()}
        <option value="left">{t('analytics.left')}</option><option value="right">{t('analytics.right')}</option>
      {/snippet}</Select></label>
      {#if config.series.length > 1}<Button size="sm" onclick={() => edit({ series: config.series.filter((_, at) => at !== index) })}>{t('analytics.remove_series')}</Button>{/if}
    {/each}
    {#if config.series.length < 12}<Button size="sm" onclick={() => edit({ series: [...config.series, { metric: analytics.catalog[0]?.id || 'total_tokens', operation: 'timeline' }] })}>{t('analytics.add_series')}</Button>{/if}
    <label>{t('analytics.display')} <Select size="sm" value={config.display.type} onchange={(event) => edit({ display: { ...config.display, type: event.currentTarget.value as ChartConfig['display']['type'] } })}>{#snippet children()}
      <option value="line">{t('analytics.line')}</option><option value="area">{t('analytics.area')}</option><option value="bar">{t('analytics.bar')}</option>
    {/snippet}</Select></label>
    <Checkbox label={t('analytics.enabled')} checked={config.enabled} onchange={(event) => edit({ enabled: event.currentTarget.checked })} />
    <Checkbox label={t('analytics.legend')} checked={config.display.legend !== false} onchange={(event) => edit({ display: { ...config.display, legend: event.currentTarget.checked } })} />
    <Checkbox label={t('analytics.indexed')} checked={config.display.indexed === true} onchange={(event) => edit({ display: { ...config.display, indexed: event.currentTarget.checked } })} />
    <Checkbox label={t('analytics.pin_time')} checked={config.range.mode === 'pinned'} onchange={(event) => edit({ range: event.currentTarget.checked ? { mode: 'pinned', ...range } : { mode: 'global' } })} />
    {#if config.range.mode === 'pinned'}
      <label>{t('analytics.from')} <Field type="datetime-local" value={localValue(config.range.from || range.from)} onchange={(event) => pinTime('from', event.currentTarget.value)} /></label>
      <label>{t('analytics.to')} <Field type="datetime-local" value={localValue(config.range.to || range.to)} onchange={(event) => pinTime('to', event.currentTarget.value)} /></label>
    {/if}
    <TripwireEditor {config} />
  </div>
  {/if}
{/snippet}

<style>
  @layer components {
    :global(.analytics-cell--tile) .analytics-headline strong { flex: none; font-size: var(--oc-fs-figure); }

    .analytics-open { position: absolute; top: var(--oc-space-2); right: var(--oc-space-2); z-index: 1; }

    @media (max-width: 1023px) {
      .analytics-open { right: 0; }
    }

    .analytics-identity { display: flex; flex-direction: column; min-width: 0; gap: var(--oc-space-1); }

    .analytics-identity strong { overflow: hidden; color: var(--oc-text-primary); font-size: var(--oc-fs-status); font-weight: 600; letter-spacing: .015em; text-overflow: ellipsis; white-space: nowrap; }

    .analytics-range { display: flex; align-items: baseline; min-width: 0; gap: var(--oc-space-2); overflow: hidden; white-space: nowrap; }

    .analytics-period--short, .analytics-range:global([data-fit='short']) .analytics-period:not(.analytics-period--short), .analytics-range:global([data-fit='short']) .analytics-asof { display: none; }
    .analytics-range:global([data-fit='short']) .analytics-period--short { display: inline; }
    .analytics-range:global([data-fit]) { flex: 0 0 auto; }
    .analytics-range:global([data-fit='none']) { display: none; }
    :global(.oc-head-group:has(> .analytics-range[data-fit='none']) + .oc-head-sep) { display: none; }

    .analytics-range span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
    .analytics-range { flex: 0 1 auto; max-width: 100%; }

    .analytics-range span, .analytics-identity span { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }
    .analytics-identity .analytics-asof, .analytics-range .analytics-asof { letter-spacing: .04em; text-transform: none; }

    .analytics-headline strong { font-size: clamp(25px, 3vw, 36px); }

    .analytics-change { color: var(--oc-text-muted); }

    .analytics-change b { font-weight: 600; }

    .analytics-change span { margin-left: .6ch; }

    .analytics-change--up b { color: var(--oc-yellow); }

    .analytics-change--down b { color: var(--oc-cyan); }

    .analytics-caveat { color: var(--oc-orange); }

    .analytics-metadata { flex: none; }

    .analytics-headline--tokens { flex-wrap: wrap; row-gap: var(--oc-space-1); white-space: normal; }

    .analytics-facts--corner { grid-template-columns: repeat(2, max-content); gap: var(--oc-space-0-5) var(--oc-space-4); flex: 0 1 auto; margin: 0 0 0 auto; font-size: var(--oc-fs-micro); line-height: 1.3; white-space: nowrap; }

    .analytics-facts--corner div { gap: var(--oc-space-2); }

    .analytics-plot.analytics-plot--yield { min-height: 0; }

    .analytics-plot.analytics-plot--dropped { flex: none; height: 0; min-height: 0; }

    .analytics-facts div, .analytics-ranking-row, .analytics-quota-legend li { display: flex; min-width: 0; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); }

    .analytics-facts dt, .analytics-ranking span { overflow: hidden; color: var(--oc-text-muted); text-overflow: ellipsis; white-space: nowrap; }

    .analytics-facts dd { margin: 0; color: var(--oc-text-primary); font-variant-numeric: tabular-nums; }

    .analytics-context { color: var(--oc-text-secondary); }

    .analytics-ranking-room { flex: 1 1 0; min-height: 0; overflow: hidden; }

    .analytics-ranking-room--free { flex: none; overflow: visible; }

    .analytics-change--cost { margin-top: var(--oc-space-0-5); }

    .analytics-ranking--bare { gap: var(--oc-space-0-5); }

    .analytics-ranking-room > .analytics-ranking:not(.analytics-ranking--bare) { display: flex; flex-direction: column; height: calc(100% - var(--oc-space-2) - var(--oc-space-1)); }

    .analytics-ranking-room > .analytics-ranking:not(.analytics-ranking--bare) li { flex: 1 0 auto; max-height: 72px; }

    .analytics-ranking > li { display: block; min-width: 0; }

    .analytics-ranking strong, .analytics-quota-legend strong { flex: none; font-weight: 500; font-variant-numeric: tabular-nums; }

    .analytics-ranking-track { height: 3px; margin-top: var(--oc-space-1); background: var(--oc-line-faint); }

    .analytics-ranking-fill { height: 100%; background: var(--oc-cyan); }

    .analytics-quota-legend { grid-template-columns: repeat(auto-fill, minmax(min(100%, 150px), 1fr)); gap: var(--oc-space-0-5) var(--oc-space-3); font-size: var(--oc-fs-micro); }

    .analytics-swatch { flex: none; width: 8px; height: 8px; border-radius: 1px; align-self: center; }

    .analytics-quota-legend li { justify-content: flex-start; }

    .analytics-quota-legend strong { margin-left: auto; }

    .analytics-quota-legend span { min-width: 0; overflow: hidden; color: var(--oc-text-muted); text-overflow: ellipsis; white-space: nowrap; }

    .analytics-plot { min-height: 70px; }

    .analytics-note { margin: var(--oc-space-2) var(--oc-widget-inset); color: var(--oc-text-muted); }

    .analytics-edit { display: flex; align-items: center; flex-wrap: wrap; gap: var(--oc-space-2); color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .analytics-edit select, .analytics-edit input { min-height: 32px; padding: var(--oc-space-0-5) var(--oc-space-2); border: 1px solid var(--oc-line-rule); border-radius: var(--oc-radius-sm); background: var(--oc-ground-raised); color: var(--oc-text-primary); font: inherit; }

    .analytics-edit label { display: flex; align-items: center; gap: var(--oc-space-1); }

  }
</style>
