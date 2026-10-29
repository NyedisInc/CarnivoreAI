/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('../cells/analytics/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  createChart: async (chart: { id: string }) => ({ ...chart, revision: 1 }),
  updateChart: async (chart: unknown) => chart,
}));
import { homeLayout } from '../engine/layout.svelte';
import { analytics } from '../cells/analytics/state.svelte';
import { staleChartIds } from '../cells/analytics/prune';
import type { ChartConfig } from '../cells/analytics/types';
import {
  addAnalyticsWidget,
  editorSeams,
  enterLayoutEditor,
  finishLayoutEditor,
  removeWidget,
  restoreAnalyticsWidget,
} from './editor.svelte';

const real = { ...editorSeams };
const slots = (): string[] => homeLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
const analyticsSlots = (): string[] => slots().filter((id) => id.startsWith('analytics:'));

beforeEach(() => {
  editorSeams.page = () => 'home';
  editorSeams.store = (p) => (p === 'home' ? homeLayout : null);
  editorSeams.wide = () => true;
  homeLayout.resetAll();
  analytics.charts = {};
  enterLayoutEditor();
});

afterEach(() => {
  finishLayoutEditor();
  Object.assign(editorSeams, real);
  analytics.charts = {};
});

describe('removing a configurable widget', () => {
  test('the definition outlives the slot, and restoring puts the same chart back', async () => {
    addAnalyticsWidget();
    const [slot] = analyticsSlots();
    const id = (slot as string).slice('analytics:'.length);
    await vi.waitFor(() => expect(analytics.charts[id]!.revision).toBe(1));
    const saved = JSON.stringify(analytics.charts[id]);
    expect(await removeWidget(slot as never)).toBe(true);
    expect(analyticsSlots()).toEqual([]);
    expect(JSON.stringify(analytics.charts[id])).toBe(saved);
    expect(restoreAnalyticsWidget(slot as never)).toBe(true);
    expect(analyticsSlots()).toEqual([slot]);
    expect(JSON.stringify(analytics.charts[id])).toBe(saved);
  });

  test('a restore with a drop target lands the chart there', async () => {
    addAnalyticsWidget();
    const [slot] = analyticsSlots();
    await removeWidget(slot as never);
    expect(restoreAnalyticsWidget(slot as never, { kind: 'new', after: null })).toBe(true);
    expect(slots()[0]).toBe(slot);
  });
});

describe('pruning stale restore entries', () => {
  const chart = (id: string, title = 'tokens'): ChartConfig =>
    ({ id, revision: 1, title, enabled: true, series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {}, range: { mode: 'global' }, display: { type: 'line', legend: true }, viz: 'timeline', options: {} }) as ChartConfig;

  test('drops unreferenced copies of a config that is kept, keeps one copy of each other config', () => {
    const charts = [chart('a'), chart('b'), chart('c'), chart('d', 'other'), chart('e', 'other')];
    expect(staleChartIds(charts, new Set(['analytics:a']))).toEqual(['b', 'c', 'e']);
  });

  test('never touches a chart any board names, hidden ones included', () => {
    const charts = [chart('a'), chart('b')];
    expect(staleChartIds(charts, new Set(['analytics:a', 'analytics:b']))).toEqual([]);
  });
});
