/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

const handlers = new Map<string, Set<(frame: unknown) => void>>();
vi.mock('../../api/events.svelte', () => ({
  subscribe: (kind: string, handler: (frame: unknown) => void) => {
    const held = handlers.get(kind) ?? new Set();
    held.add(handler);
    handlers.set(kind, held);
    return () => held.delete(handler);
  },
}));

import { COALESCE_MS, followStatsFrames } from './stats-frames';
import { analytics, applyStatsChanged, chartTick, type StatsChanged } from './state.svelte';

function emit(frame: Record<string, unknown>): void {
  for (const handler of handlers.get(String(frame.type)) ?? []) handler(frame);
}

const change = (metrics: string[], over: Partial<StatsChanged> = {}): StatsChanged =>
  ({ metrics, live: false, events: false, dimensions: false, ...over });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  handlers.clear();
});

describe('stats.changed follower', () => {
  test('merges a burst, holds while hidden, applies once on return, and a reconnect is a full refresh', () => {
    vi.useFakeTimers();
    let hidden = false;
    const applied: StatsChanged[] = [];
    const refreshAll = vi.fn();
    const stop = followStatsFrames({ refreshAll, apply: (c) => applied.push(c), hidden: () => hidden });

    emit({ type: 'stats.changed', changed: change(['total_tokens']) });
    emit({ type: 'stats.changed', changed: change(['working_seconds'], { live: true }) });
    vi.advanceTimersByTime(COALESCE_MS);
    expect(applied).toHaveLength(1);
    expect(new Set(applied[0]!.metrics)).toEqual(new Set(['total_tokens', 'working_seconds']));
    expect(applied[0]!.live).toBe(true);

    hidden = true;
    emit({ type: 'stats.changed', changed: change(['starts']) });
    vi.advanceTimersByTime(10 * 60 * 1000);
    expect(applied).toHaveLength(1);
    hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    expect(applied).toHaveLength(2);
    expect(applied[1]!.metrics).toEqual(['starts']);

    emit({ type: 'stats.changed' });
    vi.advanceTimersByTime(COALESCE_MS);
    expect(refreshAll).toHaveBeenCalledTimes(1);
    emit({ type: 'events.hello' });
    vi.advanceTimersByTime(COALESCE_MS);
    expect(refreshAll).toHaveBeenCalledTimes(2);
    expect(applied).toHaveLength(2);
    stop();
  });

  test('a chart keeps its tick unless a metric it plots moved', () => {
    analytics.refreshedAt = 1000;
    analytics.metricTicks = { working_seconds: 5000 };
    const tokens = { series: [{ metric: 'total_tokens' }] } as never;
    const working = { series: [{ metric: 'working_seconds' }] } as never;
    expect(chartTick(tokens)).toBe(1000);
    expect(chartTick(working)).toBe(5000);
  });

  test('an idle (clock-only) frame moves only its charts and makes no side read', async () => {
    const fetch = vi.fn(async (_url: string) => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    analytics.metricTicks = {};
    await applyStatsChanged(change(['observed_seconds'], { clock_only: true }));
    expect(fetch).not.toHaveBeenCalled();
    expect(analytics.metricTicks.observed_seconds).toBeGreaterThan(0);
    await applyStatsChanged(change(['total_tokens']));
    expect(fetch.mock.calls.map(([url]) => String(url)).some((url) => url.includes('/stats/coverage'))).toBe(true);
  });
});

describe('merge keeps the named side reads (#1181)', () => {
  test('coverage and tripwires OR together, and an older frame without them stays unnamed', async () => {
    const { merge } = await import('./stats-frames');
    const base = { metrics: ['total_tokens'], live: false, events: false, dimensions: false };
    const a = merge(null, { ...base, coverage: false, tripwires: false });
    const b = merge(a, { ...base, coverage: true, tripwires: false });
    expect(b !== 'full' && b !== null && [b.coverage, b.tripwires]).toEqual([true, false]);
    const older = merge(b, { ...base });
    expect(older !== 'full' && older !== null && older.coverage).toBeUndefined();
  });
});

describe('a data frame with unchanged fingerprints skips the coverage and tripwire reads (#1180)', () => {
  test('emitted through the follower, coverage:false and tripwires:false make no side read; true makes it', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async (_url: string) => new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetch);
    const stop = followStatsFrames({ refreshAll: vi.fn(), apply: (changed) => void applyStatsChanged(changed), hidden: () => false });
    const urls = (): string[] => fetch.mock.calls.map(([url]) => String(url));
    const frame = (over: Record<string, unknown>): Record<string, unknown> => ({
      type: 'stats.changed',
      changed: { metrics: ['working_seconds'], live: false, events: false, dimensions: false,
        coverage: false, tripwires: false, clock_only: false, ...over },
    });

    emit(frame({}));
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect(urls().filter((url) => url.includes('/stats/coverage') || url.includes('/stats/tripwires'))).toEqual([]);

    emit(frame({ coverage: true, tripwires: true }));
    await vi.advanceTimersByTimeAsync(COALESCE_MS);
    expect(urls().some((url) => url.includes('/stats/coverage'))).toBe(true);
    expect(urls().some((url) => url.includes('/stats/tripwires'))).toBe(true);
    stop();
  });
});
