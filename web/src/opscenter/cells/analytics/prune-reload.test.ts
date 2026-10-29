// @vitest-environment jsdom
import { beforeEach, describe, expect, test, vi } from 'vitest';
import { setHomeSeedLevel, seedControl } from '../../engine/home-seed';
import { createLayoutStore } from '../../engine/layout.svelte';
import { PRUNE_DONE_KEY } from './prune';
import type { ChartConfig } from './types';

const hoisted = vi.hoisted(() => ({ deleteChart: vi.fn(async () => undefined) }));
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), deleteChart: hoisted.deleteChart }));
vi.mock('../../viz/tripwires.svelte', () => ({ tripwires: { list: [] }, loadTripwires: async () => {} }));

const chart = (id: string): ChartConfig =>
  ({ id, revision: 1, title: 'tokens', enabled: true, series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {}, range: { mode: 'global' }, display: { type: 'line', legend: true }, viz: 'timeline', options: {} }) as ChartConfig;

async function load(referenced: string[]): Promise<void> {
  const { seedHomeAnalytics } = await import('./state.svelte');
  seedControl.attach(() => {}, () => new Set(referenced));
  seedControl.markReady();
  await seedHomeAnalytics(createLayoutStore('home'));
}

beforeEach(async () => {
  localStorage.clear();
  hoisted.deleteChart.mockClear();
  seedControl.reset();
  setHomeSeedLevel(2);
  const { analytics } = await import('./state.svelte');
  analytics.error = '';
  analytics.charts = { a: chart('a'), b: chart('b') };
});

describe('reloading after a removal', () => {
  test('a removed duplicate stays listed once the one-time sweep has run', async () => {
    await load(['analytics:a', 'analytics:b']);
    expect(localStorage.getItem(PRUNE_DONE_KEY)).toBe('done');
    await load(['analytics:a']);
    expect(hoisted.deleteChart).not.toHaveBeenCalled();
    const { analytics } = await import('./state.svelte');
    expect(Object.keys(analytics.charts)).toEqual(['a', 'b']);
  });

  test('the old stale duplicates still go on the first load', async () => {
    await load(['analytics:a']);
    expect(hoisted.deleteChart).toHaveBeenCalledWith('b', 1);
    const { analytics } = await import('./state.svelte');
    expect(Object.keys(analytics.charts)).toEqual(['a']);
  });

  test('a failed sweep is not marked done, so the next load retries', async () => {
    const { ApiError } = await import('../../api/auth.svelte');
    hoisted.deleteChart.mockRejectedValueOnce(new ApiError('boom', 500) as never);
    await load(['analytics:a']);
    expect(localStorage.getItem(PRUNE_DONE_KEY)).toBeNull();
  });
});
