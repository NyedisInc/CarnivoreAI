import type { ChartConfig, ChartSeries, QueryBody, RangePreset, StatsFilters } from '../cells/analytics/types';
import { VIZ_SPECS, vizOf } from './specs';

export const PRESET_MS: Record<RangePreset, number> = {
  '1h': 3600_000, '6h': 6 * 3600_000, '24h': 24 * 3600_000, '7d': 7 * 86400_000, '30d': 30 * 86400_000, '90d': 90 * 86400_000,
};

export interface PlanContext {
  now: number;
  timezone: string;
  filters: StatsFilters;
  quotaWindow?: string;
  marker?: { from: string; to: string } | null;
  rolling?: boolean;
}

export const DEFAULT_QUOTA_WINDOW = 'five_hour';

export function rollingPreset(config: ChartConfig, range: { from: string; to: string }, ctx: PlanContext): RangePreset | null {
  if (!ctx.rolling || ctx.marker || config.range.mode === 'pinned' || config.range.zoom) return null;
  const base = baseRange(config, ctx.now);
  if (base.from !== range.from || base.to !== range.to) return null;
  return config.range.preset && PRESET_MS[config.range.preset] ? config.range.preset : VIZ_SPECS[vizOf(config)].preset;
}

export function baseRange(config: ChartConfig, now: number): { from: string; to: string } {
  if (config.range.mode === 'pinned' && config.range.from && config.range.to) return { from: config.range.from, to: config.range.to };
  const preset = config.range.preset && PRESET_MS[config.range.preset] ? config.range.preset : VIZ_SPECS[vizOf(config)].preset;
  return { from: new Date(now - PRESET_MS[preset]).toISOString(), to: new Date(now).toISOString() };
}

export function effectiveRange(config: ChartConfig, ctx: PlanContext): { from: string; to: string } {
  return config.range.zoom ?? ctx.marker ?? baseRange(config, ctx.now);
}

export function allowedFilters(metric: string, filters: StatsFilters, quotaWindow?: string): StatsFilters {
  const keys: (keyof StatsFilters)[] = metric === 'quota_utilization' ? ['provider', 'account_id', 'window'] : ['provider', 'host', 'project', 'model', 'agent_kind', 'conversation_id'];
  const selected = Object.fromEntries(keys.filter((key) => filters[key]).map((key) => [key, filters[key]])) as StatsFilters;
  if (metric === 'quota_utilization' && !selected.window && quotaWindow) selected.window = quotaWindow;
  return selected;
}

export function mergeFilters(...layers: (object | undefined)[]): StatsFilters {
  const merged: Record<string, unknown> = {};
  for (const layer of layers) for (const [key, value] of Object.entries(layer ?? {})) if (value) merged[key] = value;
  return merged as StatsFilters;
}

export function priorRange(range: { from: string; to: string }): { from: string; to: string } {
  const span = new Date(range.to).getTime() - new Date(range.from).getTime();
  return { from: new Date(new Date(range.from).getTime() - span).toISOString(), to: range.from };
}

export function seriesBody(config: ChartConfig, series: ChartSeries, range: { from: string; to: string }, ctx: PlanContext, operation?: QueryBody['operation']): QueryBody {
  const op = operation ?? (ctx.marker ? 'comparison' : series.operation || 'timeline');
  const rolling = rollingPreset(config, range, ctx);
  return {
    metric: series.metric, operation: op, ...(rolling ? { rolling } : { from: range.from, to: range.to }), timezone: ctx.timezone,
    resolution: config.resolution ?? 'auto',
    filters: allowedFilters(series.metric, mergeFilters(ctx.filters, config.filters, series.filters), ctx.quotaWindow),
    ...(series.metric === 'quota_utilization' ? {} : { scope: 'pack' as const }),
    transform: series.transform || 'total',
    ...(series.group_by ? { group_by: series.group_by } : {}),
    ...((series.operation === 'ranking' && !series.group_by) ? { group_by: series.metric === 'quota_utilization' ? 'account_id' : 'model' } : {}),
    ...((op === 'comparison' && !rolling) ? { comparison: priorRange(range) } : {}),
  };
}

export function contextMetricsFor(primary: ChartSeries | undefined): string[] {
  if (primary?.metric === 'total_tokens' && primary.operation !== 'ranking') return ['input_tokens', 'output_tokens', 'cache_write_tokens', 'cache_read_tokens'];
  if (primary?.metric === 'working_seconds' && primary.operation !== 'ranking') return ['starts', 'completions', 'running_seconds', 'average_working_agents'];
  if (primary?.metric === 'cache_read_tokens' && primary.operation !== 'ranking') return ['input_tokens', 'cache_write_tokens'];
  return [];
}

export const COST_MODELS = 5;

export function isPlainCostSeries(series: ChartSeries | undefined): boolean {
  return series?.metric === 'estimated_cost_nano_usd' && (series.operation || 'timeline') === 'timeline' && !series.group_by;
}

function costExtraBodies(config: ChartConfig, series: ChartSeries, range: { from: string; to: string }, ctx: PlanContext, single: QueryBody): QueryBody[] {
  return [
    { ...single, operation: 'ranking', group_by: 'model', top_n: COST_MODELS },
    seriesBody(config, { ...series, operation: 'comparison', group_by: undefined }, range, ctx, 'comparison'),
  ];
}

export function timelinePlan(config: ChartConfig, ctx: PlanContext): { bodies: QueryBody[]; summary: QueryBody | null; context: QueryBody[]; all: QueryBody[] } {
  const active = config.series.filter((series) => series.visible !== false).slice(0, 12);
  const range = effectiveRange(config, ctx);
  const bodies = active.map((series) => seriesBody(config, series, range, ctx));
  const first = bodies[0];
  const { comparison: _prior, ...single } = first ?? ({} as QueryBody);
  const summary = first ? { ...single, operation: 'summary' as const } : null;
  const context: QueryBody[] = first ? contextMetricsFor(active[0]).map((metric) => ({ ...single, metric, operation: 'summary' as const, transform: 'total' as const })) : [];
  if (first && active[0] && isPlainCostSeries(active[0])) context.push(...costExtraBodies(config, active[0], range, ctx, single));
  return { bodies, summary, context, all: [...bodies, ...(summary ? [summary] : []), ...context] };
}

export function kpiPlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  const series = config.series.find((item) => item.visible !== false);
  return series ? [seriesBody(config, { ...series, operation: 'comparison', group_by: undefined }, effectiveRange(config, { ...ctx, marker: null }), ctx, 'comparison')] : [];
}

export function defaultQuotaWindow(dimensions: Record<string, { filter_value: string | null }[]>): string | undefined {
  const windows = dimensions.window ?? [];
  return (windows.find((item) => item.filter_value === 'five_hour') ?? windows.find((item) => item.filter_value))?.filter_value ?? undefined;
}

export const TREEMAP_PROVIDERS = ['claude', 'codex'] as const;
export const TREEMAP_MODELS = 4;
export const TREEMAP_PROJECTS = 6;
export const HEAT_MAX_MS = 24 * 86400_000;

export function treemapMetric(config: ChartConfig): string {
  return config.options?.measure === 'cost' ? 'estimated_cost_nano_usd' : 'total_tokens';
}

export function leaderboardTopN(config: ChartConfig): number {
  const asked = config.options?.top_n;
  return typeof asked === 'number' && asked >= 1 && asked <= 10 ? Math.floor(asked) : Number(VIZ_SPECS.leaderboard.options.top_n);
}

export function leaderboardPlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  const series = config.series.find((item) => item.visible !== false);
  if (!series) return [];
  const top_n = leaderboardTopN(config);
  const ranking = { ...seriesBody(config, { ...series, operation: 'ranking' }, effectiveRange(config, { ...ctx, marker: null }), ctx, 'ranking'), top_n };
  const { comparison: _prior, ...single } = ranking;
  return [ranking, { ...single, operation: 'timeline', top_n }];
}

export function treemapModelsPlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  const series = config.series.find((item) => item.visible !== false);
  if (!series) return [];
  const range = effectiveRange(config, { ...ctx, marker: null });
  return TREEMAP_PROVIDERS.map((provider) => ({
    ...seriesBody(config, { ...series, metric: treemapMetric(config), operation: 'ranking', group_by: 'model', filters: { ...series.filters, provider } }, range, ctx, 'ranking'),
    top_n: TREEMAP_MODELS,
  }));
}

export interface DrillTarget { provider: string; model: string }

export function treemapProjectsPlan(config: ChartConfig, ctx: PlanContext, targets: DrillTarget[]): QueryBody[] {
  const series = config.series.find((item) => item.visible !== false);
  if (!series) return [];
  const range = effectiveRange(config, { ...ctx, marker: null });
  return targets.map((target) => ({
    ...seriesBody(config, { ...series, metric: treemapMetric(config), operation: 'ranking', group_by: 'project', filters: { ...series.filters, provider: target.provider as 'claude' | 'codex', model: target.model } }, range, ctx, 'ranking'),
    top_n: TREEMAP_PROJECTS,
  }));
}

export function heatPlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  const series = config.series.find((item) => item.visible !== false);
  if (!series) return [];
  const range = effectiveRange(config, { ...ctx, marker: null });
  const to = new Date(range.to).getTime();
  const from = Math.max(new Date(range.from).getTime(), to - HEAT_MAX_MS);
  return [{ ...seriesBody(config, { ...series, operation: 'timeline', group_by: undefined }, { from: new Date(from).toISOString(), to: range.to }, ctx, 'timeline'), resolution: 'hour' }];
}

export const RUNWAY_ACCOUNTS = 10;
export const SWIMLANE_LANES = 8;

export const SWIMLANE_METRICS = ['working_seconds', 'waiting_seconds', 'subagent_seconds'] as const;

export function runwayPlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  const body = seriesBody(config, { metric: 'quota_utilization', group_by: 'account_id' }, effectiveRange(config, { ...ctx, marker: null }), ctx, 'timeline');
  return [{ ...body, top_n: RUNWAY_ACCOUNTS }];
}

export function swimlanePlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  const range = effectiveRange(config, { ...ctx, marker: null });
  return SWIMLANE_METRICS.map((metric) => ({
    ...seriesBody(config, { metric, group_by: 'conversation_id' }, range, ctx, 'timeline'),
    top_n: SWIMLANE_LANES,
  }));
}
