/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('./visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const runQueries = vi.fn();
vi.mock('./query-client', () => ({ runQueries: (...args: unknown[]) => runQueries(...args) }));
vi.mock('../cells/analytics/api', () => ({ annotations: vi.fn(async () => []) }));
vi.mock('./echarts-setup', () => ({ openChart: () => ({ dispose: () => {}, chart: { setOption: () => {}, clear: () => {}, resize: () => {} } }), tokenColors: () => (_css: string, fallback: string) => fallback }));
vi.mock('../cells/analytics/ChartCanvas.svelte', () => ({ default: () => {} }));

import TimelineView from '../cells/analytics/TimelineView.svelte';
import { analytics } from '../cells/analytics/state.svelte';
import type { ChartConfig, QueryResult } from '../cells/analytics/types';

const VALUES: Record<string, number> = { total_tokens: 5.88e9, input_tokens: 1.2e6, output_tokens: 3.4e7, cache_write_tokens: 2.5e8, cache_read_tokens: 5.5e9 };

function answer(metric: string): QueryResult {
  const value = VALUES[metric] ?? 1;
  return { metric, operation: 'summary', unit: 'tokens', resolution: 'hour' as QueryResult['resolution'],
    series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value }] }],
    summary: { value, samples: 3, contributing_conversations: 4 }, ranking: [], coverage: { minute_rows: 9 } };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
}

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; runQueries.mockReset(); vi.unstubAllGlobals(); });

async function card(tier: 'tile' | 'panel' | 'full', height: number | null): Promise<HTMLElement> {
  const config: ChartConfig = { id: 'c1', revision: 1, title: 'tokens', enabled: true, series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } };
  analytics.charts = { c1: config };
  runQueries.mockImplementation(async (items: { metric: string }[]) => items.map((item) => ({ ok: true, result: answer(item.metric) })));
  if (height !== null) {
    vi.stubGlobal('ResizeObserver', class { constructor(private cb: () => void) {} observe() { this.cb(); } disconnect() {} });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => height });
  }
  const target = document.createElement('div');
  document.body.append(target);
  mounted = mount(TimelineView, { target, props: { instance: 'analytics:c1', tier } });
  await settle();
  return target;
}

const labels = (root: HTMLElement) => [...root.querySelectorAll('.analytics-facts--tokens dt')].map((node) => node.textContent);

describe('the tokens card breakdown', () => {
  test('the headline reads billions as B', async () => {
    const root = await card('panel', 400);
    expect(root.querySelector('.analytics-headline strong')?.textContent).toBe('5.88B');
  });

  test.each([['the tile tier', 'tile', null], ['a section under 300px', 'panel', 200]] as const)('%s shows all four facts in the headline row, in order, and no context line', async (_name, tier, height) => {
    const root = await card(tier, height);
    expect(labels(root)).toEqual(['fresh input', 'output', 'cache write', 'cache read']);
    expect(root.querySelector('.analytics-headline .analytics-facts--corner')).not.toBeNull();
    expect(root.querySelector('.analytics-context')).toBeNull();
    expect(root.querySelector('.analytics-headline')).not.toBeNull();
  });

  test('a card with room keeps the plain row and the context line', async () => {
    const root = await card('full', 400);
    expect(labels(root)).toHaveLength(4);
    expect(root.querySelector('.analytics-headline .analytics-facts--corner')).not.toBeNull();
    expect(root.querySelector('.analytics-context')).not.toBeNull();
  });
});
