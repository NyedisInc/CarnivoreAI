import { t } from '../i18n/index.svelte';
import { FEED_WINDOWS, RATE_UNITS, type FeedBody, type FeedClasses, type FeedWindow, type RateUnit } from './types';

const UNIT_SECONDS: Readonly<Record<RateUnit, number>> = { sec: 1, min: 60, hour: 3600, day: 86400 };

export function next<T>(order: readonly T[], current: T): T {
  const at = order.indexOf(current);
  return order[(at + 1) % order.length] as T;
}

export const nextUnit = (unit: RateUnit): RateUnit => next(RATE_UNITS, unit);
export const nextWindow = (window: FeedWindow): FeedWindow => next(FEED_WINDOWS, window);

export function tokensIn(c: FeedClasses | null | undefined): number | null {
  return c ? c.fresh + c.cache_write + c.cache_read : null;
}

export function rateIn(body: FeedBody | null, unit: RateUnit): { out: number; in: number } | null {
  const rate = body?.rate;
  if (!rate) return null;
  const f = UNIT_SECONDS[unit];
  return { out: rate.out * f, in: (tokensIn(rate) ?? 0) * f };
}

const SI_STEPS: readonly [number, string][] = [[1e12, 'viz.si_t'], [1e9, 'viz.si_b'], [1e6, 'viz.si_m'], [1e3, 'viz.si_k']];

export function compact(value: number): string {
  const abs = Math.abs(value);
  const digits = (n: number): string => new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(n);
  for (const [size, key] of SI_STEPS) if (abs >= size) return t(key, { value: digits(value / size) });
  return digits(value);
}

export interface ChartBar {
  total: number | null;
  in: number | null;
  out: number | null;
  at: number;
}

export function chartBars(body: FeedBody | null): ChartBar[] {
  if (!body) return [];
  return body.in.map((i, n) => {
    const o = body.out[n] ?? null;
    return { total: i === null && o === null ? null : (i ?? 0) + (o ?? 0), in: i, out: o, at: body.start + n * body.bucket_seconds };
  });
}

export interface MergedBar extends ChartBar {
  end: number;
  count: number;
}

export function mergeBars(bars: ChartBar[], maxBars: number, bucketSeconds: number): MergedBar[] {
  const group = Math.max(1, Math.ceil(bars.length / Math.max(1, maxBars)));
  const out: MergedBar[] = [];
  for (let hi = bars.length; hi > 0; hi -= group) {
    const part = bars.slice(Math.max(0, hi - group), hi);
    const measured = part.filter((b) => b.total !== null);
    const sum = (pick: (b: ChartBar) => number | null): number | null =>
      measured.length ? measured.reduce((acc, b) => acc + (pick(b) ?? 0), 0) : null;
    const first = part[0];
    const last = part[part.length - 1];
    if (!first || !last) continue;
    out.unshift({
      total: sum((b) => b.total), in: sum((b) => b.in), out: sum((b) => b.out),
      at: first.at, end: last.at + bucketSeconds, count: part.length,
    });
  }
  return out;
}

const DOWN_WORDS: readonly string[] = ['unreachable', 'refused', 'not_supported'];

export interface Missing {
  from: number;
  down: boolean;
}

export function missingSpan(body: FeedBody | null): Missing | null {
  if (!body || body.state !== 'partial') return null;
  const away = body.sources.filter((s) => s.host_key !== 'local' && s.state !== 'ok');
  if (away.length === 0) return null;
  const from = Math.min(...away.map((s) => s.data_through ?? body.start));
  return { from: Math.max(from, body.start), down: away.some((s) => DOWN_WORDS.includes(s.state)) };
}
