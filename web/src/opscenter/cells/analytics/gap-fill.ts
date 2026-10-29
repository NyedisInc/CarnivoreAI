/* nothing at all */

const GAUGES = new Set(['quota_utilization', 'average_working_agents', 'average_running_agents']);

export function zeroFills(metric: string, transform: string | undefined): boolean {
  return !GAUGES.has(metric) && transform !== 'per_conversation';
}

export interface Observation { earliest: number | null; off: { from: number; to: number }[] }

export function observationOf(coverage: { earliest?: string | null; disabled_spans?: { from: string; to: string | null }[] } | null | undefined, now: number): Observation | null {
  if (!coverage) return null;
  const earliest = coverage.earliest ? Date.parse(coverage.earliest) : NaN;
  const off = (coverage.disabled_spans ?? []).map((span) => ({ from: Date.parse(span.from), to: span.to ? Date.parse(span.to) : now }))
    .filter((span) => Number.isFinite(span.from) && Number.isFinite(span.to) && span.to > span.from);
  return { earliest: Number.isFinite(earliest) ? earliest : null, off };
}

export function watched(at: number, bucketMs: number, seen: Observation | null): boolean {
  if (!seen) return true;
  const end = at + Math.max(1, bucketMs);
  if (seen.earliest !== null && end <= seen.earliest) return false;
  return !seen.off.some((span) => span.from <= at && span.to >= end);
}

export function filledValue(value: number | null, time: string | number, fill: boolean, now: number,
  seen: Observation | null = null, bucketMs = 0): number | null {
  if (value !== null || !fill) return value;
  const at = typeof time === 'number' ? time : Date.parse(time);
  return Number.isFinite(at) && at <= now && watched(at, bucketMs, seen) ? 0 : null;
}

export function bucketMsOf(points: readonly { time: string | number }[]): number {
  if (points.length < 2) return 0;
  const at = (time: string | number): number => typeof time === 'number' ? time : Date.parse(time);
  const step = at(points[1]!.time) - at(points[0]!.time);
  return Number.isFinite(step) && step > 0 ? step : 0;
}

export function unobservedSpans(from: number, to: number, seen: Observation | null): { from: number; to: number }[] {
  if (!seen || !(to > from)) return [];
  const spans = [...(seen.earliest !== null && seen.earliest > from ? [{ from, to: Math.min(to, seen.earliest) }] : []),
    ...seen.off.map((span) => ({ from: Math.max(from, span.from), to: Math.min(to, span.to) }))];
  return spans.filter((span) => span.to > span.from).sort((a, b) => a.from - b.from);
}
