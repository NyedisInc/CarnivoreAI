/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const runQueries = vi.fn();
vi.mock('../../viz/query-client', () => ({ runQueries: (...args: unknown[]) => runQueries(...args) }));
vi.mock('./api', () => ({ annotations: vi.fn(async () => []) }));
vi.mock('./ChartCanvas.svelte', () => ({ default: ($$anchor: Comment) => { const mark = document.createElement('i'); mark.dataset.chart = ''; $$anchor.before(mark); } }));

import TimelineView from './TimelineView.svelte';
import { analytics } from './state.svelte';
import { MIN_PLOT_HEIGHT_PX, chartFits } from './plot-fit';
import type { ChartConfig, QueryResult } from './types';

const answer = (metric: string): QueryResult => ({ metric, operation: 'summary', unit: 'tokens', resolution: 'hour' as QueryResult['resolution'],
  series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value: 5 }] }], summary: { value: 5, samples: 3, contributing_conversations: 4 }, ranking: [], coverage: { minute_rows: 9 } });

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; runQueries.mockReset(); vi.unstubAllGlobals(); });

async function tile(plotHeight: number, plotTop = 400 - plotHeight - 3): Promise<HTMLElement> {
  analytics.charts = { c1: { id: 'c1', revision: 1, title: 'tokens', enabled: true, series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as ChartConfig };
  runQueries.mockImplementation(async (items: { metric: string }[]) => items.map((item) => ({ ok: true, result: answer(item.metric) })));
  vi.stubGlobal('ResizeObserver', class { constructor(private cb: () => void) {} observe() { this.cb(); } disconnect() {} });
  const realStyle = window.getComputedStyle.bind(window);
  vi.stubGlobal('getComputedStyle', (node: Element, pseudo?: string | null) => (node.classList.contains('analytics-plot') ? { marginBottom: '3px' } as CSSStyleDeclaration : realStyle(node, pseudo)));
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get(this: HTMLElement) { return this.classList.contains('analytics-plot') ? plotHeight : 400; } });
  Object.defineProperty(HTMLElement.prototype, 'offsetTop', { configurable: true, get(this: HTMLElement) { return this.classList.contains('analytics-plot') ? plotTop : 0; } });
  const target = document.createElement('div');
  document.body.append(target);
  mounted = mount(TimelineView, { target, props: { instance: 'analytics:c1', tier: 'tile' } });
  for (let i = 0; i < 8; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
  return target;
}

describe('the plot fit rule', () => {
  test('a box under the floor cannot hold a chart, an unmeasured one is held back', () => {
    expect(chartFits(MIN_PLOT_HEIGHT_PX - 1)).toBe(false);
    expect(chartFits(MIN_PLOT_HEIGHT_PX)).toBe(true);
    expect(chartFits(null)).toBe(false);
  });

  test('a collapsed plot drops the chart and keeps the breakdown', async () => {
    const root = await tile(0);
    expect(root.querySelector('[data-chart]')).toBeNull();
    expect(root.querySelectorAll('.analytics-facts--tokens dt')).toHaveLength(4);
  });

  test('a collapsed band remounts the chart once the room below it, less its 3px margin, reaches the floor', async () => {
    const root = await tile(0, 400 - MIN_PLOT_HEIGHT_PX - 3);
    expect(root.querySelector('[data-chart]')).not.toBeNull();
  });

  test('a collapsed band one pixel short of the floor stays collapsed', async () => {
    const root = await tile(0, 400 - MIN_PLOT_HEIGHT_PX - 3 + 1);
    expect(root.querySelector('[data-chart]')).toBeNull();
  });

  test('a plot with room mounts the chart', async () => {
    const root = await tile(MIN_PLOT_HEIGHT_PX);
    expect(root.querySelector('[data-chart]')).not.toBeNull();
  });

  test('a row that mounts after the band and later leaves gives the chart back', async () => {
    let extra = 0;
    const observed = new Set<Element>();
    const callbacks: Array<() => void> = [];
    vi.stubGlobal('ResizeObserver', class { constructor(private cb: () => void) { callbacks.push(cb); } observe(node: Element) { observed.add(node); this.cb(); } disconnect() {} });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get(this: HTMLElement) { return this.classList.contains('analytics-plot') ? (400 - 320 - extra >= 70 ? 400 - 320 - extra : 0) : 400; } });
    Object.defineProperty(HTMLElement.prototype, 'offsetTop', { configurable: true, get(this: HTMLElement) { return this.classList.contains('analytics-plot') ? 320 + extra : 0; } });
    const realStyle = window.getComputedStyle.bind(window);
    vi.stubGlobal('getComputedStyle', (node: Element, pseudo?: string | null) => (node.classList.contains('analytics-plot') ? { marginBottom: '3px' } as CSSStyleDeclaration : realStyle(node, pseudo)));
    analytics.charts = { c1: { id: 'c1', revision: 1, title: 'tokens', enabled: true, series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as ChartConfig };
    runQueries.mockImplementation(async (items: { metric: string }[]) => items.map((item) => ({ ok: true, result: answer(item.metric) })));
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(TimelineView, { target, props: { instance: 'analytics:c1', tier: 'tile' } });
    const settle = async () => { for (let i = 0; i < 8; i += 1) { await tick(); await Promise.resolve(); } flushSync(); };
    await settle();
    expect(target.querySelector('.analytics-plot--dropped')).toBeNull();
    const card = target.querySelector('.analytics-plot')!.parentElement!;
    const row = document.createElement('p');
    card.insertBefore(row, target.querySelector('.analytics-plot'));
    extra = 30;
    await settle();
    expect(observed.has(row)).toBe(true);
    expect(target.querySelector('.analytics-plot--dropped')).not.toBeNull();
    row.remove();
    extra = 0;
    await settle();
    expect(target.querySelector('.analytics-plot--dropped')).toBeNull();
  });
});
