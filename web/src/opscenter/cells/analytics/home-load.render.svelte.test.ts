/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const hoisted = vi.hoisted(() => ({
  authFetch: vi.fn(),
  chart: { props: null as null | { results: { metric: string }[] } },
}));
vi.mock('../../api/auth.svelte', () => ({ authFetch: hoisted.authFetch, ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
vi.mock('../../viz/echarts-setup', () => ({ openChart: () => ({ dispose: () => {}, chart: { setOption: () => {}, clear: () => {}, resize: () => {} } }), tokenColors: () => (_css: string, fallback: string) => fallback }));
vi.mock('./plot-fit', () => ({ chartFits: () => true, plotBoxHeight: () => 200 }));
vi.mock('./ChartCanvas.svelte', () => ({ default: (_anchor: unknown, props: { results: { metric: string }[] }) => { hoisted.chart.props = props; } }));

import TimelineView from './TimelineView.svelte';
import { analytics, refreshAnalytics } from './state.svelte';
import { resetSnapshotMemory } from './snapshot';
import type { ChartConfig, QueryBody, QueryResult } from './types';

const authFetch = hoisted.authFetch;
const base = { revision: 1, enabled: true, filters: {}, range: { mode: 'global' as const }, display: { type: 'line' as const } };
const CHARTS: ChartConfig[] = [
  { ...base, id: 'c1', title: 'tokens', series: [{ metric: 'total_tokens', operation: 'timeline' }] },
  { ...base, id: 'c2', title: 'cost', series: [{ metric: 'estimated_cost_nano_usd', operation: 'timeline' }] },
  { ...base, id: 'c3', title: 'activity', series: [{ metric: 'working_seconds', operation: 'timeline' }] },
  { ...base, id: 'c4', title: 'models', series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'model' }] },
  { ...base, id: 'c5', title: 'projects', series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'project' }] },
  { ...base, id: 'c6', title: 'agents', series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'agent_kind' }] },
  { ...base, id: 'c7', title: 'quota', series: [{ metric: 'quota_utilization', operation: 'timeline', group_by: 'account_id' }] },
];

function answer(item: QueryBody): QueryResult {
  const value = 100;
  return { metric: item.metric, operation: item.operation, unit: 'tokens', resolution: 'hour',
    series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value }] }],
    summary: { value, samples: 3, contributing_conversations: 4 }, ranking: [{ key: 'a', label: 'a', value }], coverage: { minute_rows: 9 } };
}

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));
async function settle(ms = 120): Promise<void> { await wait(ms); flushSync(); }

const mounted: Record<string, unknown>[] = [];
function card(id: string): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TimelineView, { target, props: { instance: `analytics:${id}`, tier: 'panel' as const } }));
  return target;
}
afterEach(() => { mounted.splice(0).forEach((one) => unmount(one)); document.body.innerHTML = ''; authFetch.mockReset(); hoisted.chart.props = null; localStorage.clear(); resetSnapshotMemory(); });

describe('the Home load', () => {
  test('seven cards send one batch, ahead of the coverage and dimension reads and unmoved when they land', async () => {
    const batches: QueryBody[][] = [];
    const side = { coverage: false, dimensions: false };
    let open!: () => void;
    const gate = new Promise<void>((resolve) => { open = resolve; });
    authFetch.mockImplementation(async (path: string, init?: { body?: string }) => {
      if (path === '/stats/charts') return CHARTS;
      if (path === '/stats/catalog') return [];
      if (path === '/stats/settings') return { enabled: true, revision: 1 };
      if (path === '/stats/coverage') { await gate; side.coverage = true; return { minute_rows: 1 }; }
      if (path.startsWith('/stats/dimensions')) { await gate; side.dimensions = true; return { items: [{ key: 'five_hour', label: '5-hour', filter_value: 'five_hour' }] }; }
      if (path === '/stats/query-batch') {
        const items = (JSON.parse(init?.body ?? '{}') as { items: QueryBody[] }).items;
        batches.push(items);
        return { results: items.map((item) => ({ ok: true, result: answer(item), answer: { as_of: new Date().toISOString(), stale: false, reason: null } })) };
      }
      if (path.startsWith('/stats/events')) return { items: [] };
      if (path === '/stats/tripwires') return [];
      return {};
    });
    void refreshAnalytics();
    await settle(60);
    expect(side).toEqual({ coverage: false, dimensions: false });
    expect(Object.keys(analytics.charts)).toHaveLength(7);
    CHARTS.forEach((chart) => card(chart.id));
    await settle();
    expect(batches).toHaveLength(1);
    expect(batches[0]!.length).toBeGreaterThanOrEqual(7);
    expect(batches[0]!.every((item) => item.rolling && item.from === undefined && item.to === undefined)).toBe(true);
    open();
    await settle();
    expect(side).toEqual({ coverage: true, dimensions: true });
    expect(batches).toHaveLength(1);
  });
});

describe('a card never goes blank', () => {
  const two: ChartConfig = { ...base, id: 'two', title: 'two series', series: [{ metric: 'total_tokens', operation: 'timeline' }, { metric: 'estimated_cost_nano_usd', operation: 'timeline' }] };

  function serve(failing: { on: boolean }): void {
    authFetch.mockImplementation(async (path: string, init?: { body?: string }) => {
      if (path === '/stats/query-batch') {
        const items = (JSON.parse(init?.body ?? '{}') as { items: QueryBody[] }).items;
        return { results: items.map((item) => (failing.on && item.metric === 'estimated_cost_nano_usd'
          ? { ok: false, error: { code: 'stats_query_limit', message: 'too slow' } }
          : { ok: true, result: answer(item) })) };
      }
      return path.startsWith('/stats/events') ? { items: [] } : {};
    });
  }

  test('one failed series leaves the other series drawn', async () => {
    analytics.charts = { two };
    serve({ on: true });
    card('two');
    await settle();
    expect(hoisted.chart.props?.results.map((one) => one.metric)).toEqual(['total_tokens']);
  });

  test('a failed refresh keeps the last good chart and says how old it is', async () => {
    analytics.charts = { two };
    const failing = { on: false };
    serve(failing);
    const root = card('two');
    await settle();
    expect(hoisted.chart.props?.results).toHaveLength(2);
    expect(root.querySelector('.analytics-asof')).toBeNull();
    failing.on = true;
    analytics.refreshedAt = Date.now() + 1000;
    await settle();
    expect(hoisted.chart.props?.results).toHaveLength(2);
    expect(root.querySelector('.analytics-asof')?.textContent).toMatch(/^as of /);
  });
});

describe('a cold tab', () => {
  test('paints the saved snapshot before the network answers', async () => {
    const tokens = CHARTS[0]!;
    analytics.charts = { c1: tokens };
    authFetch.mockImplementation(async (path: string, init?: { body?: string }) => {
      if (path === '/stats/query-batch') {
        const items = (JSON.parse(init?.body ?? '{}') as { items: QueryBody[] }).items;
        return { results: items.map((item) => ({ ok: true, result: answer(item) })) };
      }
      return path.startsWith('/stats/events') ? { items: [] } : {};
    });
    card('c1');
    await settle(700);
    expect(localStorage.getItem('carnivore.analytics.snapshot')).toContain('"c1"');
    mounted.splice(0).forEach((one) => unmount(one));
    document.body.innerHTML = '';
    resetSnapshotMemory();
    authFetch.mockImplementation((path: string) => (path === '/stats/query-batch' ? new Promise(() => {}) : Promise.resolve(path.startsWith('/stats/events') ? { items: [] } : {})));
    const root = card('c1');
    await settle();
    expect(root.querySelector('.analytics-headline strong')?.textContent).not.toBe('');
    expect(root.querySelector('.analytics-headline')).not.toBeNull();
    expect(root.querySelector('.analytics-asof')?.textContent).toMatch(/^as of /);
    expect(root.textContent).not.toContain('loading history');
  });
});
