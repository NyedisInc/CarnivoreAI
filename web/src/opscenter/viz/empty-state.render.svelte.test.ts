/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-out' } }));
vi.mock('./visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const runQueries = vi.fn();
vi.mock('./query-client', () => ({ runQueries: (...args: unknown[]) => runQueries(...args) }));
vi.mock('../cells/analytics/api', () => ({ annotations: vi.fn(async () => []) }));
vi.mock('./echarts-setup', () => ({ openChart: () => ({ dispose: () => {}, chart: { setOption: () => {}, clear: () => {}, resize: () => {} } }), tokenColors: () => (_css: string, fallback: string) => fallback }));
vi.mock('../cells/analytics/ChartCanvas.svelte', () => ({ default: () => {} }));

import TimelineView from '../cells/analytics/TimelineView.svelte';
import KpiRenderer from './KpiRenderer.svelte';
import { analytics } from '../cells/analytics/state.svelte';
import type { ChartConfig, QueryResult } from '../cells/analytics/types';
import { emptyTopic, isBlank, seriesBlank } from './empty';

function chart(id: string, metric: string, operation: 'timeline' | 'ranking' = 'timeline'): ChartConfig {
  return { id, revision: 1, title: metric, enabled: true, series: [{ metric, operation }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } };
}

function blank(metric: string, unit = 'tokens'): QueryResult {
  return { metric, operation: 'summary', unit, resolution: 'hour' as QueryResult['resolution'],
    series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value: null }] }],
    summary: { value: null, samples: 0, contributing_conversations: 0 }, ranking: [],
    coverage: { minute_rows: 0, priced_token_total: 0 } };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
}

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; runQueries.mockReset(); });

describe('the analytics empty state', () => {
  test.each([
    ['total_tokens', 'timeline', 'token use shows here'],
    ['estimated_cost_nano_usd', 'timeline', 'estimated cost shows here'],
    ['working_seconds', 'timeline', 'working time shows here'],
    ['total_tokens', 'ranking', 'rows fill in'],
  ] as const)('an empty %s %s card says one calm line and nothing else', async (metric, operation, line) => {
    analytics.charts = { c1: chart('c1', metric, operation) };
    runQueries.mockImplementation(async (items: unknown[]) => items.map(() => ({ ok: true, result: blank(metric) })));
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(TimelineView, { target, props: { instance: 'analytics:c1', tier: 'panel' } });
    await settle();
    const text = target.textContent ?? '';
    const empties = target.querySelectorAll('.viz-empty');
    expect(empties).toHaveLength(1);
    expect(empties[0]!.textContent).toContain(line);
    expect(text).not.toMatch(/no data|no observations|unknown|\b0 (contributing|priced)/);
    expect(target.querySelector('.analytics-headline')).toBeNull();
  });

  test('a card with real usage keeps its headline and shows no empty line', async () => {
    analytics.charts = { c1: chart('c1', 'total_tokens') };
    const full: QueryResult = { ...blank('total_tokens'), series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value: 4200 }] }],
      summary: { value: 4200, samples: 3, contributing_conversations: 2 }, coverage: { minute_rows: 9 } };
    runQueries.mockImplementation(async (items: unknown[]) => items.map(() => ({ ok: true, result: full })));
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(TimelineView, { target, props: { instance: 'analytics:c1', tier: 'panel' } });
    await settle();
    expect(target.querySelector('.viz-empty')).toBeNull();
    expect(target.querySelector('.analytics-headline')?.textContent).toContain('4.2k');
  });

  test('an empty kpi says one line instead of a giant blank figure', async () => {
    runQueries.mockImplementation(async () => [{ ok: true, result: { ...blank('total_tokens'), comparison: null } }]);
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(KpiRenderer, { target, props: { config: { ...chart('k1', 'total_tokens'), viz: 'kpi' }, tier: 'full' } });
    await settle();
    expect(target.querySelectorAll('.viz-empty')).toHaveLength(1);
    expect(target.querySelector('.viz-kpi__figure')).toBeNull();
    expect(target.textContent).not.toMatch(/no data/);
  });

  test('the helpers: zero and null are blank, metric families pick their line', () => {
    expect(isBlank(null)).toBe(true);
    expect(isBlank(0)).toBe(true);
    expect(isBlank(3)).toBe(false);
    expect(seriesBlank([{ series: [{ points: [{ value: 0 }, { value: null }] }] }])).toBe(true);
    expect(seriesBlank([{ series: [{ points: [{ value: 1 }] }] }])).toBe(false);
    expect(emptyTopic('estimated_cost_nano_usd')).toBe('cost');
    expect(emptyTopic('quota_utilization')).toBe('quota');
    expect(emptyTopic('cache_read_tokens')).toBe('tokens');
    expect(emptyTopic('working_seconds')).toBe('activity');
    expect(emptyTopic('total_tokens', true)).toBe('ranking');
  });
});
