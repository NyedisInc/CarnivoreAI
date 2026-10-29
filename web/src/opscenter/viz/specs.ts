import type { ChartConfig, RangePreset, Viz } from '../cells/analytics/types';

export type { Viz };
export const VIZ_KINDS: readonly Viz[] = ['timeline', 'kpi', 'leaderboard', 'treemap', 'heat', 'vitals', 'hot', 'events', 'fleet', 'runway', 'swimlanes', 'flow', 'scatter', 'impact', 'health', 'pack', 'agents'];

export interface VizSpec {
  min: { width: number; height: number };
  options: Record<string, unknown>;
  preset: RangePreset;
}

export const VIZ_SPECS: Readonly<Record<Viz, VizSpec>> = {
  timeline: { min: { width: 260, height: 120 }, options: {}, preset: '24h' },
  kpi: { min: { width: 140, height: 90 }, options: { compare_prior: true }, preset: '24h' },
  leaderboard: { min: { width: 220, height: 110 }, options: { top_n: 8 }, preset: '7d' },
  treemap: { min: { width: 220, height: 130 }, options: { measure: 'tokens' }, preset: '7d' },
  heat: { min: { width: 260, height: 130 }, options: {}, preset: '7d' },
  vitals: { min: { width: 200, height: 90 }, options: {}, preset: '1h' },
  hot: { min: { width: 220, height: 110 }, options: {}, preset: '1h' },
  events: { min: { width: 220, height: 110 }, options: {}, preset: '24h' },
  fleet: { min: { width: 200, height: 90 }, options: {}, preset: '1h' },
  runway: { min: { width: 220, height: 110 }, options: {}, preset: '6h' },
  swimlanes: { min: { width: 260, height: 120 }, options: {}, preset: '6h' },
  flow: { min: { width: 260, height: 130 }, options: { measure: 'tokens' }, preset: '7d' },
  scatter: { min: { width: 240, height: 130 }, options: {}, preset: '7d' },
  impact: { min: { width: 240, height: 130 }, options: { annotation_id: '', metric: 'estimated_cost_nano_usd', days: 7 }, preset: '7d' },
  health: { min: { width: 220, height: 110 }, options: {}, preset: '1h' },
  pack: { min: { width: 240, height: 110 }, options: {}, preset: '1h' },
  agents: { min: { width: 260, height: 200 }, options: {}, preset: '24h' },
};

export const UNION_MIN = {
  width: Math.min(...VIZ_KINDS.map((kind) => VIZ_SPECS[kind].min.width)),
  height: Math.min(...VIZ_KINDS.map((kind) => VIZ_SPECS[kind].min.height)),
};

export function vizOf(config: Pick<ChartConfig, 'viz'>): Viz {
  return config.viz && config.viz in VIZ_SPECS ? config.viz : 'timeline';
}

export function isCompactTimeline(config: ChartConfig): boolean {
  if (vizOf(config) !== 'timeline') return false;
  const first = config.series.find((series) => series.visible !== false);
  if (!first) return false;
  const operation = first.operation || 'timeline';
  return operation === 'ranking' || (first.metric === 'estimated_cost_nano_usd' && operation === 'timeline' && !first.group_by);
}

export const COMPACT_TIMELINE_MIN = { width: 200, height: 54 } as const;

export function vizFloor(config: ChartConfig): { width: number; height: number } {
  return isCompactTimeline(config) ? COMPACT_TIMELINE_MIN : VIZ_SPECS[vizOf(config)].min;
}
