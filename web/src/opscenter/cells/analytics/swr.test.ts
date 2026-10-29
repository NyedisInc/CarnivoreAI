import { describe, expect, test } from 'vitest';
import { holdWhileRefreshing, mergeDimensions, planShape } from './swr';
import type { QueryBody } from './types';

const body = (from: string, to: string): QueryBody => ({
  metric: 'total_tokens', operation: 'timeline', from, to, timezone: 'UTC', resolution: 'auto', filters: {}, transform: 'total',
});

describe('stale while revalidate', () => {
  test('a rolling window tick keeps the same card shape', () => {
    const a = planShape([body('2026-09-29T00:00:00Z', '2026-09-30T00:00:00Z')], ['input_tokens']);
    const b = planShape([body('2026-09-29T00:01:00Z', '2026-09-30T00:01:00Z')], ['input_tokens']);
    expect(a).toBe(b);
  });

  test('a changed metric is a different shape', () => {
    const other = { ...body('x', 'y'), metric: 'estimated_cost_nano_usd' };
    expect(planShape([body('x', 'y')], [])).not.toBe(planShape([other], []));
  });

  test('a known value is never regressed to empty on refetch of the same card', () => {
    const shape = planShape([body('a', 'b')], []);
    expect(holdWhileRefreshing(shape, shape, 42, null)).toBe(42);
  });

  test('unknown only when never loaded or the card changed', () => {
    const shape = planShape([body('a', 'b')], []);
    expect(holdWhileRefreshing(null, shape, 42, null)).toBeNull();
    expect(holdWhileRefreshing(shape, 'other', 42, null)).toBeNull();
  });

  test('a failed dimension read keeps the previous list', () => {
    const previous = { window: [{ filter_value: 'five_hour', label: '5h' }] } as never;
    const merged = mergeDimensions(previous, ['window', 'model'], [
      { status: 'rejected', reason: new Error('boom') },
      { status: 'fulfilled', value: [] },
    ]);
    expect(merged.window).toHaveLength(1);
    expect(merged.model).toEqual([]);
  });
});
