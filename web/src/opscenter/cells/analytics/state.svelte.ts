import { createChart, deleteChart, dimensionValues, getChart, listCharts, metricCatalog, updateChart } from './api';
import { agentsUpgrade } from './agents-upgrade';
import { mergeDimensions } from './swr';
import { loadTripwires, tripwires } from '../../viz/tripwires.svelte';
import type { ChartConfig, DimensionItem, MetricCatalogEntry, StatsFilters } from './types';
import { ApiError, authFetch } from '../../api/auth.svelte';
import { t } from '../../../lib/i18n/index.svelte';
import { flushSave } from '../../engine/persist';
import { homeHasSyncedBoards, homeReferencedAnalytics, homeSeedLevel, setHomeSeedLevel, whenHomeSyncReady } from '../../engine/home-seed';
import { markPruneDone, pruneAlreadyDone, staleChartIds } from './prune';
import type { LayoutStore } from '../../engine/layout.svelte';
import type { SlotId } from '../../engine/types';
import { drawerEnv } from '../../../lib/drawer/env';
import { whenLegacyBootComplete } from '../../../lib/legacy-boot';
import { explicitHostId, normalizeHostFiltersForSave } from '../../viz/plan';
import { selfHostInstallId } from './host-id.svelte';

export const ANALYTICS_FILTERS_PREF_FIELD = 'analytics_filters';
export const ANALYTICS_TIMEZONE_PREF_FIELD = 'analytics_timezone';
export const ANALYTICS_PREF_WRITE_DELAY_MS = 400;

export const GLOBAL_FILTER_KEYS = ['provider', 'host', 'project', 'model', 'agent_kind', 'account_id', 'window'] as const;
export type GlobalFilterKey = (typeof GLOBAL_FILTER_KEYS)[number];

interface AnalyticsPrefsApi {
  HYDRATED?: unknown;
  status?(): unknown;
  get?(field: string, fallback?: unknown): unknown;
  committedValue?(field: string): unknown;
  set?(field: string, value: unknown): Promise<unknown>;
  subscribe?(fn: (name: string, value: unknown) => void): () => void;
}

interface AnalyticsBridgeApi {
  read?(field: string, fallback: () => unknown): unknown;
  write?(field: string, value: unknown, local: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

interface AnalyticsPrefGlobals {
  PreferenceBridge?: AnalyticsBridgeApi;
  Preferences?: AnalyticsPrefsApi;
}

function prefGlobals(): AnalyticsPrefGlobals {
  return drawerEnv() as AnalyticsPrefGlobals;
}

export function parseAnalyticsFilters(raw: unknown): StatsFilters | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  const out: StatsFilters = {};
  for (const key of GLOBAL_FILTER_KEYS) {
    const val = obj[key];
    if (typeof val === 'string') {
      const trimmed = val.trim();
      if (trimmed && trimmed.length <= 256) out[key] = trimmed;
    }
  }
  return out;
}

export function parseAnalyticsTimezone(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const tz = raw.trim();
  if (!tz || tz.length > 64) return null;
  if (tz === 'UTC') return tz;
  try {
    Intl.DateTimeFormat(undefined, { timeZone: tz });
    return tz;
  } catch {
    return null;
  }
}

function cleanFilters(filters: StatsFilters): StatsFilters {
  const out: StatsFilters = {};
  for (const key of GLOBAL_FILTER_KEYS) {
    const val = filters[key];
    if (typeof val === 'string' && val.trim()) out[key] = val.trim();
  }
  return out;
}

function readSharedPref(field: string): unknown {
  const g = prefGlobals();
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.read === 'function') return bridge.read(field, () => undefined);
  const prefs = g.Preferences;
  if (!prefs) return undefined;
  if (typeof prefs.status === 'function' && prefs.status() !== (prefs.HYDRATED ?? 'hydrated')) return undefined;
  if (typeof prefs.get === 'function') return prefs.get(field, undefined);
  if (typeof prefs.committedValue === 'function') return prefs.committedValue(field);
  return undefined;
}

function writeSharedPref(field: string, value: unknown): void {
  const g = prefGlobals();
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.write === 'function') {
    bridge.write(field, value, () => {}).catch((err: unknown) => {
      console.warn(`Analytics: could not share ${field}:`, err);
    });
    return;
  }
  const prefs = g.Preferences;
  if (prefs && typeof prefs.set === 'function'
      && (typeof prefs.status !== 'function' || prefs.status() === (prefs.HYDRATED ?? 'hydrated'))) {
    prefs.set(field, value).catch((err: unknown) => {
      console.warn(`Analytics: could not share ${field}:`, err);
    });
  }
}

let applyingRemotePrefs = false;
let filtersWriteTimer: ReturnType<typeof setTimeout> | null = null;
let timezoneWriteTimer: ReturnType<typeof setTimeout> | null = null;

function applyRemoteFilters(raw: unknown): boolean {
  const parsed = parseAnalyticsFilters(raw);
  if (parsed === null) return false;
  if (JSON.stringify(cleanFilters(analytics.filters)) === JSON.stringify(parsed)) return false;
  applyingRemotePrefs = true;
  try {
    if (filtersWriteTimer !== null) {
      clearTimeout(filtersWriteTimer);
      filtersWriteTimer = null;
    }
    analytics.filters = parsed;
    analytics.revision++;
  } finally {
    applyingRemotePrefs = false;
  }
  return true;
}

function applyRemoteTimezone(raw: unknown): boolean {
  const parsed = parseAnalyticsTimezone(raw);
  if (parsed === null || analytics.timezone === parsed) return false;
  applyingRemotePrefs = true;
  try {
    if (timezoneWriteTimer !== null) {
      clearTimeout(timezoneWriteTimer);
      timezoneWriteTimer = null;
    }
    analytics.timezone = parsed;
    analytics.revision++;
  } finally {
    applyingRemotePrefs = false;
  }
  return true;
}

export function setAnalyticsFilter(key: GlobalFilterKey, value: string): void {
  const resolved = key === 'host'
    ? explicitHostId(value.trim() || undefined, selfHostInstallId())
    : (value.trim() || undefined);
  const next = cleanFilters(analytics.filters);
  if (resolved) next[key] = resolved;
  else delete next[key];
  analytics.filters = next;
  analytics.revision++;
  if (applyingRemotePrefs) return;
  if (filtersWriteTimer !== null) clearTimeout(filtersWriteTimer);
  filtersWriteTimer = setTimeout(() => {
    filtersWriteTimer = null;
    writeSharedPref(ANALYTICS_FILTERS_PREF_FIELD, cleanFilters(analytics.filters));
  }, ANALYTICS_PREF_WRITE_DELAY_MS);
}

export function setAnalyticsTimezone(timezone: string): void {
  const parsed = parseAnalyticsTimezone(timezone);
  if (!parsed) return;
  analytics.timezone = parsed;
  analytics.revision++;
  if (applyingRemotePrefs) return;
  if (timezoneWriteTimer !== null) clearTimeout(timezoneWriteTimer);
  timezoneWriteTimer = setTimeout(() => {
    timezoneWriteTimer = null;
    writeSharedPref(ANALYTICS_TIMEZONE_PREF_FIELD, analytics.timezone);
  }, ANALYTICS_PREF_WRITE_DELAY_MS);
}

export function syncAnalyticsPrefsFromPreferences(): void {
  applyRemoteFilters(readSharedPref(ANALYTICS_FILTERS_PREF_FIELD));
  applyRemoteTimezone(readSharedPref(ANALYTICS_TIMEZONE_PREF_FIELD));
}

export function startAnalyticsPrefsSync(
  target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
  syncAnalyticsPrefsFromPreferences();
  const g = prefGlobals();
  const unsubs: Array<() => void> = [];
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.follow === 'function') {
    unsubs.push(bridge.follow(ANALYTICS_FILTERS_PREF_FIELD, (value) => { applyRemoteFilters(value); }));
    unsubs.push(bridge.follow(ANALYTICS_TIMEZONE_PREF_FIELD, (value) => { applyRemoteTimezone(value); }));
  } else if (g.Preferences && typeof g.Preferences.subscribe === 'function') {
    unsubs.push(g.Preferences.subscribe((name, value) => {
      if (name === ANALYTICS_FILTERS_PREF_FIELD) applyRemoteFilters(value);
      else if (name === ANALYTICS_TIMEZONE_PREF_FIELD) applyRemoteTimezone(value);
    }));
  }
  let stopped = false;
  whenLegacyBootComplete(target, () => {
    if (!stopped) syncAnalyticsPrefsFromPreferences();
  });
  return () => {
    stopped = true;
    for (const stop of unsubs) stop();
  };
}

export function resetAnalyticsPrefsSync(): void {
  if (filtersWriteTimer !== null) {
    clearTimeout(filtersWriteTimer);
    filtersWriteTimer = null;
  }
  if (timezoneWriteTimer !== null) {
    clearTimeout(timezoneWriteTimer);
    timezoneWriteTimer = null;
  }
  applyingRemotePrefs = false;
}

export const analytics = $state<{
  charts: Record<string, ChartConfig>;
  catalog: MetricCatalogEntry[];
  enabled: boolean;
  settingsRevision: number;
  filters: StatsFilters;
  dimensions: Record<string, DimensionItem[]>;
  timezone: string;
  revision: number;
  tickAt: number;
  refreshedAt: number;
  metricTicks: Record<string, number>;
  error: string;
  loaded: boolean;
  coverage: { earliest?: string | null; latest?: string | null; freshness_seconds?: number | null; minute_rows?: number; quality_rows?: number; unknown_cost_rows?: number; disabled_spans?: { from: string; to: string | null }[]; sources?: { status: string; quality: string; count: number }[]; backfill?: Record<string, number>; db_bytes?: number; collector?: unknown } | null;
}>({ charts: {}, catalog: [], enabled: true, settingsRevision: 0,
  filters: {}, dimensions: {},
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  revision: 0, tickAt: Date.now(), refreshedAt: Date.now(), metricTicks: {}, error: '', loaded: false, coverage: null });

let seeding: Promise<void> | null = null;

const DEFAULT_CHARTS = [
  { metric: 'total_tokens', operation: 'timeline', title: 'analytics.token_history' },
  { metric: 'estimated_cost_nano_usd', operation: 'timeline', title: 'analytics.cost_history' },
  { metric: 'total_tokens', operation: 'ranking', group_by: 'project', title: 'analytics.project_ranking' },
  { metric: 'total_tokens', operation: 'ranking', group_by: 'model', title: 'analytics.model_ranking' },
  { metric: 'total_tokens', operation: 'timeline', group_by: 'conversation_id', title: 'analytics.agent_ranking', viz: 'agents' },
] as const;

function matchesPreset(chart: ChartConfig, preset: typeof DEFAULT_CHARTS[number]): boolean {
  return chart.series.length === 1 && chart.series[0]?.metric === preset.metric
    && (chart.series[0].operation || 'timeline') === preset.operation
    && (chart.series[0].group_by || '') === ('group_by' in preset ? preset.group_by : '');
}

export function seedHomeAnalytics(store: LayoutStore): Promise<void> {
  if (seeding) return seeding;
  seeding = (async () => {
    await whenHomeSyncReady();
    await pruneStaleCharts();
    await upgradeAgentCharts();
    if (homeSeedLevel() >= 2 || analytics.error) return;
    if (Object.keys(analytics.charts).length > 0 || homeHasSyncedBoards()) return;
    const added: SlotId[] = [];
    const firstUpgradeDone = homeSeedLevel() >= 1;
    const firstSeed = homeSeedLevel() === 0;
    const storeHasAnalytics = store.state.layout.rows.some((row) => row.slots.some((slot) => slot.id.startsWith('analytics:')))
      || store.state.layout.hidden.some((id) => id.startsWith('analytics:'));
    if (firstSeed && storeHasAnalytics) return;
    for (const preset of DEFAULT_CHARTS) {
      if (firstUpgradeDone && (preset.metric === 'total_tokens' || preset.metric === 'estimated_cost_nano_usd') && preset.operation === 'timeline' && !('group_by' in preset)) continue;
      const ids = new Set(store.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id)).concat(store.state.layout.hidden));
      const matching = Object.values(analytics.charts).find((chart) => matchesPreset(chart, preset));
      if (matching && !ids.has(`analytics:${matching.id}`)) continue;
      if (matching) continue;
      let chart: ChartConfig;
      {
        const fresh = newChart();
        fresh.title = t(preset.title);
        fresh.series = [{ metric: preset.metric, operation: preset.operation,
          ...('group_by' in preset ? { group_by: preset.group_by } : {}) }];
        fresh.display = { type: preset.operation === 'ranking' ? 'bar' : 'line', legend: true };
        if ('viz' in preset) { fresh.viz = preset.viz; fresh.options = {}; fresh.range = { mode: 'global', preset: '1h' }; }
        try {
          chart = await createChart(fresh);
          analytics.charts[chart.id] = chart;
        } catch (error) {
          const next = { ...analytics.charts }; delete next[fresh.id]; analytics.charts = next;
          throw error;
        }
      }
      const slot = `analytics:${chart.id}` as const;
      if (!ids.has(slot)) added.push(slot);
    }
    if (added.length && !store.insertAnalytics(added, firstSeed)) throw new Error('could not place analytics charts');
    flushSave('home');
    setHomeSeedLevel(2);
  })().catch((error: unknown) => {
    analytics.error = error instanceof Error ? error.message : t('analytics.chart_unavailable');
  }).finally(() => { seeding = null; });
  return seeding;
}

async function upgradeAgentCharts(): Promise<void> {
  if (analytics.error) return;
  for (const chart of Object.values(analytics.charts)) {
    const next = agentsUpgrade(chart);
    if (!next) continue;
    try {
      analytics.charts[chart.id] = await updateChart(next);
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    }
  }
}

async function pruneStaleCharts(): Promise<void> {
  const referenced = homeReferencedAnalytics();
  if (!referenced || analytics.error || pruneAlreadyDone()) return;
  const withTripwire = new Set(tripwires.list.map((wire) => wire.chart_id));
  let complete = true;
  for (const id of staleChartIds(Object.values(analytics.charts), referenced)) {
    if (withTripwire.has(id)) continue;
    try {
      await deleteChart(id, analytics.charts[id]!.revision);
      const next = { ...analytics.charts };
      delete next[id];
      analytics.charts = next;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      complete = false;
    }
  }
  if (complete) markPruneDone();
}

let loadedAt = 0;

async function fetchAnalytics(): Promise<void> {
  try {
    const [charts, catalog, settings] = await Promise.all([
      listCharts(), metricCatalog(), authFetch<{ enabled: boolean; revision: number }>('/stats/settings'),
    ]);
    analytics.charts = Object.fromEntries(charts.map((chart) => [chart.id, viewTimers.has(chart.id) && analytics.charts[chart.id] ? analytics.charts[chart.id]! : chart]));
    analytics.catalog = catalog;
    analytics.enabled = settings.enabled;
    analytics.settingsRevision = settings.revision;
    analytics.error = '';
    analytics.loaded = true;
    const first = loadedAt === 0;
    if (first) loadedAt = Date.now();
    else if (Date.now() - loadedAt > INITIAL_HELLO_MS) requestTick('all');
    void loadSideReads();
  } catch (error) { analytics.error = error instanceof Error ? error.message : t('analytics.chart_unavailable'); }
}

export const INITIAL_HELLO_MS = 15_000;

const DIMENSION_NAMES = ['provider', 'host', 'project', 'model', 'agent_kind', 'account_id', 'window'];

async function loadSideReads(): Promise<void> {
  const names = DIMENSION_NAMES;
  const from = new Date(Date.now() - 24 * 3600_000).toISOString();
  const to = new Date().toISOString();
  void loadTripwires();
  const [coverage, ...values] = await Promise.allSettled([
    authFetch<typeof analytics.coverage>('/stats/coverage'),
    ...names.map((name) => dimensionValues(name, from, to)),
  ]);
  if (coverage.status === 'fulfilled') analytics.coverage = coverage.value;
  analytics.dimensions = mergeDimensions(analytics.dimensions, names, values as PromiseSettledResult<DimensionItem[]>[]);
}

export const REQUERY_MIN_MS = 60_000;

let lastRelease = 0;
let releaseTimer: ReturnType<typeof setTimeout> | null = null;
let pendingAll = false;
const pendingMetrics = new Set<string>();

function requestTick(what: string[] | 'all'): void {
  if (what === 'all') pendingAll = true;
  else for (const metric of what) pendingMetrics.add(metric);
  if (releaseTimer !== null) return;
  const wait = lastRelease + REQUERY_MIN_MS - Date.now();
  if (wait <= 0) release();
  else releaseTimer = setTimeout(release, wait);
}

function release(): void {
  releaseTimer = null;
  const now = Date.now();
  if (pendingAll) analytics.refreshedAt = now;
  if (pendingMetrics.size > 0) {
    const ticks = { ...analytics.metricTicks };
    for (const metric of pendingMetrics) ticks[metric] = now;
    analytics.metricTicks = ticks;
  }
  analytics.tickAt = now;
  pendingAll = false;
  pendingMetrics.clear();
  lastRelease = now;
}

let pendingRefresh: Promise<void> | null = null;

export function refreshAnalytics(): Promise<void> {
  if (pendingRefresh) return pendingRefresh;
  pendingRefresh = fetchAnalytics().finally(() => { pendingRefresh = null; });
  return pendingRefresh;
}

export interface StatsChanged {
  metrics: string[];
  live: boolean;
  events: boolean;
  dimensions: boolean;
  coverage?: boolean;
  tripwires?: boolean;
  clock_only?: boolean;
}

export function chartTick(config: Pick<ChartConfig, 'series'> | undefined): number {
  const metrics = (config?.series ?? []).map((series) => series.metric);
  if (metrics.length === 0) return analytics.tickAt;
  return Math.max(analytics.refreshedAt, ...metrics.map((metric) => analytics.metricTicks[metric] ?? 0));
}

export async function applyStatsChanged(changed: StatsChanged | undefined): Promise<void> {
  if (!changed) return refreshAnalytics();
  const now = Date.now();
  if (changed.metrics.length > 0) requestTick(changed.metrics);
  const reads: Promise<void>[] = [];
  const dataMoved = changed.metrics.length > 0 && !changed.clock_only;
  if (changed.coverage ?? dataMoved) {
    reads.push(authFetch<typeof analytics.coverage>('/stats/coverage').then((coverage) => { analytics.coverage = coverage; }));
  }
  if (changed.tripwires ?? dataMoved) reads.push(loadTripwires());
  if (changed.dimensions) {
    const names = DIMENSION_NAMES;
    reads.push(Promise.allSettled(names.map((name) => dimensionValues(name, new Date(now - 24 * 3600_000).toISOString(), new Date(now).toISOString())))
      .then((values) => { analytics.dimensions = mergeDimensions(analytics.dimensions, names, values); }));
  }
  await Promise.allSettled(reads);
}

export async function setCollectionEnabled(enabled: boolean): Promise<void> {
  const saved = await authFetch<{ enabled: boolean; revision: number }>('/stats/settings', {
    method: 'PATCH', body: JSON.stringify({ enabled, revision: analytics.settingsRevision }),
  });
  analytics.enabled = saved.enabled;
  analytics.settingsRevision = saved.revision;
}

export async function requestBackfill(): Promise<void> {
  await authFetch<unknown>('/stats/backfill', { method: 'POST', body: JSON.stringify({ idempotency_key: analyticsId() }) });
  analytics.coverage = await authFetch<typeof analytics.coverage>('/stats/coverage');
}

export function changeChart(chart: ChartConfig): void {
  analytics.charts = { ...analytics.charts, [chart.id]: structuredClone($state.snapshot(chart)) };
}

const VIEW_SAVE_DELAY_MS = 600;
const viewTimers = new Map<string, ReturnType<typeof setTimeout>>();

function normalizeChartHostFilters(chart: ChartConfig): ChartConfig {
  const selfId = selfHostInstallId();
  if (!selfId) return chart;
  return {
    ...chart,
    filters: normalizeHostFiltersForSave(chart.filters, selfId),
    series: chart.series.map((series) => (series.filters ? { ...series, filters: normalizeHostFiltersForSave(series.filters, selfId) } : series)),
  };
}

export function saveChartView(id: string, mutate: (chart: ChartConfig) => ChartConfig): void {
  const current = analytics.charts[id];
  if (!current) return;
  changeChart(normalizeChartHostFilters(mutate(structuredClone($state.snapshot(current)))));
  const pending = viewTimers.get(id);
  if (pending) clearTimeout(pending);
  viewTimers.set(id, setTimeout(() => { viewTimers.delete(id); void writeChartView(id); }, VIEW_SAVE_DELAY_MS));
}

export function flushChartView(id: string): Promise<void> {
  const pending = viewTimers.get(id);
  if (!pending) return Promise.resolve();
  clearTimeout(pending);
  viewTimers.delete(id);
  return writeChartView(id);
}

const settingsPending = new Set<string>();

export function saveChartSettings(chart: ChartConfig): void {
  settingsPending.add(chart.id);
  saveChartView(chart.id, () => chart);
}

async function writeChartView(id: string): Promise<void> {
  await creating.get(id);
  const local = analytics.charts[id];
  if (!local) return;
  if (unsaved.has(id)) {
    try {
      const saved = await createChart($state.snapshot(local) as ChartConfig);
      unsaved.delete(id);
      analytics.charts[id] = { ...local, revision: saved.revision };
    } catch (error) { analytics.error = error instanceof Error ? error.message : t('analytics.chart_unavailable'); }
    return;
  }
  const whole = settingsPending.delete(id);
  try {
    let saved: ChartConfig;
    try { saved = await updateChart($state.snapshot(local) as ChartConfig); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409) throw error;
      const server = await getChart(id);
      saved = await updateChart(whole
        ? { ...($state.snapshot(local) as ChartConfig), revision: server.revision }
        : { ...server, filters: local.filters, range: local.range, resolution: local.resolution,
          display: { ...server.display, hidden_series: local.display.hidden_series ?? [] } });
    }
    analytics.charts[id] = viewTimers.has(id) ? { ...analytics.charts[id]!, revision: saved.revision } : saved;
  } catch (error) { analytics.error = error instanceof Error ? error.message : t('analytics.chart_unavailable'); }
}

const unsaved = new Set<string>();

const creating = new Map<string, Promise<void>>();

export function addChart(copy?: ChartConfig): ChartConfig {
  const chart = normalizeChartHostFilters(newChart(copy));
  changeChart(chart);
  const done = createChart($state.snapshot(chart) as ChartConfig).then((saved) => {
    const local = analytics.charts[chart.id];
    if (local) analytics.charts[chart.id] = { ...local, revision: saved.revision };
  }).catch((error: unknown) => {
    unsaved.add(chart.id);
    analytics.error = error instanceof Error ? error.message : t('analytics.chart_unavailable');
  }).finally(() => { creating.delete(chart.id); });
  creating.set(chart.id, done);
  return chart;
}

export function newChart(copy?: ChartConfig): ChartConfig {
  const chart: ChartConfig = copy ? structuredClone($state.snapshot(copy)) : {
    id: '', revision: 0, title: t('analytics.token_history'), enabled: true,
    series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {},
    range: { mode: 'global' }, display: { type: 'line', legend: true }, viz: 'timeline', options: {},
  };
  chart.id = analyticsId();
  chart.revision = 0;
  changeChart(chart);
  return chart;
}

function analyticsId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
