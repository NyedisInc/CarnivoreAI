import type { ChartConfig, ChartSeries, QueryBody } from '../cells/analytics/types';
import { seriesBody, type PlanContext } from './plan';

export interface Tripwire {
  id: string;
  chart_id: string | null;
  name: string;
  query: Record<string, unknown>;
  window_minutes: number;
  comparator: '>' | '<';
  threshold: number;
  for_minutes: number;
  cooldown_minutes: number;
  enabled: boolean;
  state: 'ok' | 'firing' | 'unknown';
  since: number;
  last_value: number | null;
}

export type TripwireWrite = Pick<Tripwire, 'name' | 'query' | 'window_minutes' | 'comparator' | 'threshold' | 'for_minutes' | 'cooldown_minutes' | 'enabled'> & { chart_id: string | null };

export interface TripwireFrame {
  id?: string;
  state?: string;
  value?: number | null;
  threshold?: number;
  comparator?: string;
}

export interface Alarm { state: 'ok' | 'firing' | 'unknown'; wire: Tripwire | null }

export interface DisplayUnit { factor: number; caption: string }

export function displayUnit(unit: string): DisplayUnit {
  const base = unit.split('/')[0] ?? unit;
  if (base === 'nano_usd') return { factor: 1e9, caption: 'usd' };
  if (base === 'fraction') return { factor: 0.01, caption: '%' };
  return { factor: 1, caption: base === 'tokens' ? '' : base };
}

function clean(value: number): number { return Number(value.toPrecision(12)); }

export function toStored(display: number, unit: string): number { return clean(display * displayUnit(unit).factor); }

export function toDisplay(stored: number, unit: string): number { return clean(stored / displayUnit(unit).factor); }

export function applyFrame(list: Tripwire[], frame: TripwireFrame): Tripwire[] {
  if (!frame.id || (frame.state !== 'firing' && frame.state !== 'ok')) return list;
  const state = frame.state;
  if (!list.some((wire) => wire.id === frame.id)) return list;
  return list.map((wire) => wire.id !== frame.id ? wire : {
    ...wire, state, last_value: typeof frame.value === 'number' ? frame.value : wire.last_value,
    threshold: typeof frame.threshold === 'number' ? frame.threshold : wire.threshold,
    comparator: frame.comparator === '>' || frame.comparator === '<' ? frame.comparator : wire.comparator,
  });
}

export function alarmFor(list: Tripwire[], chartId: string): Alarm {
  const mine = list.filter((wire) => wire.chart_id === chartId && wire.enabled);
  const firing = mine.find((wire) => wire.state === 'firing');
  if (firing) return { state: 'firing', wire: firing };
  const unknown = mine.find((wire) => wire.state === 'unknown');
  return unknown ? { state: 'unknown', wire: unknown } : { state: 'ok', wire: mine[0] ?? null };
}

export function seriesUnit(units: Record<string, string>, series: ChartSeries): string {
  const base = units[series.metric] ?? '';
  return series.transform === 'rate' ? `${base}/second` : series.transform === 'per_conversation' ? `${base}/conversation` : base;
}

export function tripwireQuery(config: ChartConfig, series: ChartSeries, ctx: PlanContext): Record<string, unknown> {
  const now = new Date(ctx.now).toISOString();
  const body: Partial<QueryBody> = seriesBody(config, series, { from: now, to: now }, { ...ctx, marker: null }, 'summary');
  const { from: _from, to: _to, comparison: _comparison, group_by: _group, top_n: _top, ...rest } = body;
  return { ...rest, operation: 'summary' };
}

export function thresholdLines(list: Tripwire[], chartId: string, metric: string, unit: string, indexed: boolean): number[] {
  if (indexed) return [];
  return list.filter((wire) => wire.chart_id === chartId && wire.enabled && wire.query.metric === metric)
    .map((wire) => unit.startsWith('nano_usd') ? wire.threshold / 1e9 : wire.threshold);
}
