import type { Annotation, ChartConfig } from '../cells/analytics/types';

export const IMPACT_METRICS = ['estimated_cost_nano_usd', 'total_tokens', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'usage_count'] as const;
export const IMPACT_DAYS = [1, 3, 7, 14, 30] as const;
export const IMPACT_MARKER_SPAN_MS = 90 * 86400_000;

export interface ImpactSide { from: number; to: number; n: number; conversations: number; median: number | null; partial?: boolean }
export interface ImpactPayload {
  annotation: { id: string; label: string; kind: string; reference: string | null; occurred_at: number };
  metric: string; unit: string; days: number;
  before: ImpactSide; after: ImpactSide & { partial: boolean };
  delta: { absolute: number | null; percent: number | null };
  interval: { low: number; high: number; level: number; iterations: number; seed: number } | null;
  mix: { distance: number | null; shifted: boolean; models: { model: string; model_label?: string | null; before: number; after: number }[] };
  verdict: 'insufficient' | 'higher' | 'lower' | 'no_clear_change';
  subsampled: boolean;
}

export function pickMarker(markers: readonly Pick<Annotation, 'id' | 'occurred_at'>[], chosen: string, nowSeconds: number): string | null {
  if (chosen) return chosen;
  const past = markers.filter((marker) => marker.occurred_at < nowSeconds).sort((a, b) => b.occurred_at - a.occurred_at);
  return past[0]?.id ?? null;
}

export function impactMetric(config: ChartConfig): string {
  const asked = config.options?.metric;
  return IMPACT_METRICS.includes(asked as (typeof IMPACT_METRICS)[number]) ? (asked as string) : IMPACT_METRICS[0];
}

export function impactDays(config: ChartConfig): number {
  const asked = config.options?.days;
  return typeof asked === 'number' && asked >= 1 && asked <= 30 ? Math.floor(asked) : 7;
}

export function impactPath(markerId: string, metric: string, days: number): string {
  return `/stats/impact?${new URLSearchParams({ annotation_id: markerId, metric, days: String(days) }).toString()}`;
}

export interface ImpactModel {
  verdict: ImpactPayload['verdict'];
  before: number | null;
  after: number | null;
  change: number | null;
  low: number | null;
  high: number | null;
  nBefore: number;
  nAfter: number;
  partial: boolean;
  mixShifted: boolean;
  mover: { model: string; before: number; after: number } | null;
  subsampled: boolean;
}

export function impactModel(payload: ImpactPayload | null): ImpactModel | null {
  if (!payload) return null;
  return {
    verdict: payload.verdict, before: payload.before.median, after: payload.after.median, change: payload.delta.percent,
    low: payload.interval?.low ?? null, high: payload.interval?.high ?? null,
    nBefore: payload.before.n, nAfter: payload.after.n, partial: payload.after.partial,
    mixShifted: payload.mix.shifted, mover: payload.mix.shifted && payload.mix.models[0] ? { ...payload.mix.models[0], model: payload.mix.models[0].model_label || payload.mix.models[0].model } : null, subsampled: payload.subsampled,
  };
}
