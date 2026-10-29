// @vitest-environment jsdom
import { beforeEach, expect, test, vi } from 'vitest';
import { META } from '../../engine/meta';
import { resetLayout } from '../../engine/model';
import { flushSave, STORAGE_KEYS } from '../../engine/persist';
import { createLayoutStore } from '../../engine/layout.svelte';
import type { ChartConfig } from './types';

const createChart = vi.fn(async (chart: ChartConfig) => ({ ...chart, revision: 1 }));
vi.mock('./api', () => ({ createChart }));

beforeEach(() => { localStorage.clear(); createChart.mockClear(); });

test('upgrades a customized saved home once, preserves original geometry, and respects removal', async () => {
  const original = resetLayout(META, 'home');
  original.rows[0]!.size += 27;
  const split = original.rows.find((row) => row.slots.length === 2)!;
  split.slots[0]!.fr = 0.65;
  split.slots[1]!.fr = 0.35;
  localStorage.setItem(STORAGE_KEYS.home, JSON.stringify(original));
  const { analytics, seedHomeAnalytics } = await import('./state.svelte');
  analytics.charts = {};
  analytics.error = '';
  const store = createLayoutStore('home');
  const before = JSON.parse(JSON.stringify(store.state.layout)) as typeof original;
  await seedHomeAnalytics(store);
  expect(createChart).toHaveBeenCalledTimes(5);
  const rows = store.state.layout.rows.filter((item) => item.slots.some((slot) => slot.id.startsWith('analytics:')));
  const row = rows[0]!;
  expect(store.state.layout.rows.indexOf(row)).toBe(0);
  expect(rows.map((item) => item.slots.length)).toEqual([2, 2, 1]);
  for (const old of before.rows) {
    const current = store.state.layout.rows.find((item) => item.id === old.id)!;
    expect(current).toEqual(old);
  }
  expect(createLayoutStore('home').state.layout).toEqual(store.state.layout);
  store.remove(row.slots[0]!.id);
  flushSave('home');
  const removed = createLayoutStore('home');
  await seedHomeAnalytics(removed);
  expect(createChart).toHaveBeenCalledTimes(5);
  expect(removed.state.layout.rows.flatMap((item) => item.slots.map((slot) => slot.id))).not.toContain(row.slots[0]!.id);
});

test('second upgrade preserves charts removed after the first upgrade', async () => {
  localStorage.setItem('cloudecode.opscenter.home-analytics.v1', 'done');
  const { analytics, seedHomeAnalytics } = await import('./state.svelte');
  analytics.charts = {};
  analytics.error = '';
  const store = createLayoutStore('home');
  const earlier = ['10101010-1010-4010-8010-101010101010', '20202020-2020-4020-8020-202020202020'] as const;
  expect(store.insertAnalytics(earlier.map((id) => `analytics:${id}` as const))).toBe(true);
  await seedHomeAnalytics(store);
  expect(createChart).toHaveBeenCalledTimes(3);
  const metrics = createChart.mock.calls.map(([chart]) => [chart.series[0]?.metric, chart.series[0]?.operation, chart.series[0]?.group_by]);
  expect(metrics).not.toContainEqual(['estimated_cost_nano_usd', 'timeline', undefined]);
  expect(metrics).not.toContainEqual(['total_tokens', 'timeline', undefined]);
  const rows = store.state.layout.rows;
  const earlierAt = rows.findIndex((row) => row.slots.some((slot) => slot.id === `analytics:${earlier[0]}`));
  expect(rows[earlierAt + 1]?.slots.every((slot) => slot.id.startsWith('analytics:'))).toBe(true);
  expect(rows.flatMap((row) => row.slots).filter((slot) => slot.id.startsWith('analytics:'))).toHaveLength(5);
});
