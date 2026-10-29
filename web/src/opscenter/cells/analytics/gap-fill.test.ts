import { describe, expect, test } from 'vitest';
import { bucketMsOf, filledValue, observationOf, unobservedSpans, watched, zeroFills } from './gap-fill';

const NOW = Date.parse('2026-10-01T12:00:00Z');

describe('timeline gap fill', () => {
  test('an additive series draws an empty past bucket as zero', () => {
    expect(zeroFills('total_tokens', 'total')).toBe(true);
    expect(zeroFills('compactions', undefined)).toBe(true);
    expect(filledValue(null, '2026-10-01T03:00:00Z', true, NOW)).toBe(0);
  });

  test('a gauge or a per conversation ratio keeps its gap', () => {
    expect(zeroFills('quota_utilization', 'total')).toBe(false);
    expect(zeroFills('total_tokens', 'per_conversation')).toBe(false);
    expect(filledValue(null, '2026-10-01T03:00:00Z', false, NOW)).toBeNull();
  });

  test('a future bucket is never filled and a real value is never touched', () => {
    expect(filledValue(null, '2026-10-01T13:00:00Z', true, NOW)).toBeNull();
    expect(filledValue(7, '2026-10-01T03:00:00Z', true, NOW)).toBe(7);
  });

  test('a watched bucket with nothing in it is a real zero; time before the first minute stays a gap', () => {
    const seen = observationOf({ earliest: '2026-10-01T06:00:00Z', disabled_spans: [] }, NOW);
    const hour = 3_600_000;
    expect(filledValue(null, '2026-10-01T08:00:00Z', true, NOW, seen, hour)).toBe(0);
    expect(filledValue(null, '2026-10-01T04:00:00Z', true, NOW, seen, hour)).toBeNull();
    expect(filledValue(null, '2026-10-01T05:30:00Z', true, NOW, seen, hour)).toBe(0);
  });

  test('a span the store records collection off is a gap and a hatched band, its edges are zero', () => {
    const seen = observationOf({ earliest: '2026-09-30T00:00:00Z', disabled_spans: [{ from: '2026-10-01T02:00:00Z', to: '2026-10-01T05:00:00Z' }] }, NOW);
    const hour = 3_600_000;
    expect(watched(Date.parse('2026-10-01T03:00:00Z'), hour, seen)).toBe(false);
    expect(filledValue(null, '2026-10-01T03:00:00Z', true, NOW, seen, hour)).toBeNull();
    expect(filledValue(null, '2026-10-01T05:00:00Z', true, NOW, seen, hour)).toBe(0);
    expect(unobservedSpans(Date.parse('2026-10-01T00:00:00Z'), NOW, seen)).toEqual([{ from: Date.parse('2026-10-01T02:00:00Z'), to: Date.parse('2026-10-01T05:00:00Z') }]);
  });

  test('an open off span runs to now, unknown coverage means watched, bucket length comes from the points', () => {
    const seen = observationOf({ disabled_spans: [{ from: '2026-10-01T10:00:00Z', to: null }] }, NOW);
    expect(seen?.off[0]?.to).toBe(NOW);
    expect(observationOf(null, NOW)).toBeNull();
    expect(filledValue(null, '2026-10-01T03:00:00Z', true, NOW, null, 3_600_000)).toBe(0);
    expect(bucketMsOf([{ time: '2026-10-01T00:00:00Z' }, { time: '2026-10-01T01:00:00Z' }])).toBe(3_600_000);
    expect(unobservedSpans(0, 100, { earliest: 40, off: [] })).toEqual([{ from: 0, to: 40 }]);
  });
});

