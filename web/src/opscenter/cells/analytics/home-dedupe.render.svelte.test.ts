/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount, type Component } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const runQueries = vi.fn();
vi.mock('../../viz/query-client', () => ({ runQueries: (...args: unknown[]) => runQueries(...args) }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('./api', () => ({ annotations: vi.fn(async () => []) }));
vi.mock('./ChartCanvas.svelte', () => ({ default: ($$anchor: Comment) => { const mark = document.createElement('i'); mark.dataset.chart = ''; $$anchor.before(mark); } }));

import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import AnalyticsCell from './Cell.svelte';
import { analytics } from './state.svelte';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();
import { tripwires } from '../../viz/tripwires.svelte';
import { PRESETS } from '../../viz/presets';
import type { SlotId } from '../../engine/types';
import type { CellProps } from '../../lib/cell';
import type { ChartConfig, QueryResult } from './types';

const CARDS: { id: string; title: string; series: ChartConfig['series'] }[] = [
  { id: 'tokens', title: 'tokens used', series: [{ metric: 'total_tokens', operation: 'timeline' }] },
  { id: 'cost', title: 'estimated cost', series: [{ metric: 'estimated_cost_nano_usd', operation: 'timeline' }] },
  { id: 'project', title: 'tokens by project', series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'project' }] },
  { id: 'model', title: 'tokens by model', series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'model' }] },
  { id: 'kind', title: 'tokens by agent kind', series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'agent_kind' }] },
];

let withOffline = false;
const answer = (metric: string, operation: string): QueryResult => ({ metric, operation: operation as QueryResult['operation'], unit: 'tokens', resolution: 'hour' as QueryResult['resolution'],
  series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value: 5 }] }], summary: { value: 5, samples: 3, contributing_conversations: 4 },
  ranking: [{ key: 'a', label: 'Cobalt', value: 9 }], coverage: { minute_rows: 9, unpriced_usage_count: 75 }, ...(withOffline ? { pack: { offline: [{ id: 'install-studio', label: 'studio', through: '2026-10-12T14:05:00Z' }] } } : {}) } as unknown as QueryResult);

let app: Record<string, unknown> | null = null;
beforeEach(() => {
  withOffline = false;
  tripwires.list = [];
  const realStyle = window.getComputedStyle.bind(window);
  vi.stubGlobal('getComputedStyle', (node: Element, pseudo?: string | null) => (node.classList.contains('analytics-plot') ? { marginBottom: '3px' } as CSSStyleDeclaration : realStyle(node, pseudo)));
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get(this: HTMLElement) { return this.classList.contains('analytics-plot') ? 120 : 400; } });
  Object.defineProperty(HTMLElement.prototype, 'offsetTop', { configurable: true, get(this: HTMLElement) { return this.classList.contains('analytics-plot') ? 200 : 0; } });
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; runQueries.mockReset(); vi.unstubAllGlobals(); });

async function card(entry: typeof CARDS[number]): Promise<HTMLElement> {
  analytics.charts = { [entry.id]: { id: entry.id, revision: 1, title: entry.title, enabled: true, series: entry.series, filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as ChartConfig };
  runQueries.mockImplementation(async (items: { metric: string; operation: string }[]) => items.map((item) => ({ ok: true, result: answer(item.metric, item.operation) })));
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(CellInFrame, { target, props: { slot: `analytics:${entry.id}` as SlotId, cell: AnalyticsCell as unknown as Component<CellProps> } });
  for (let i = 0; i < 10; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
  return target;
}

describe('the range label and the expand button', () => {
  for (const entry of CARDS) {
    test(`${entry.title}: both sit in the header, none in the body`, async () => {
      const root = await card(entry);
      const head = root.querySelector('[data-widget-head]')!;
      expect(head.querySelector('.analytics-range')?.textContent).toContain('24 hours');
      expect(head.querySelector('.analytics-range')?.textContent).not.toContain('past');
      expect(head.querySelector('[data-analytics-open]')).not.toBeNull();
      expect(root.querySelector('.analytics-cell [data-analytics-open]')).toBeNull();
      expect(root.querySelector('.analytics-heading')).toBeNull();
    });
  }
});

describe('the expand button is also a menu item (spec section 11 rule 3)', () => {
  test('the widget menu declares expand, so a header turned off loses no function', async () => {
    const root = await card(CARDS[0]!);
    root.querySelector<HTMLButtonElement>('[data-corner]')!.click();
    flushSync();
    expect(document.querySelector('.acm-menu [data-node="expand"]')?.textContent).toContain('expand');
  });
});

describe('an offline computer leaves no tag on the card', () => {
  test('tokens by project: a result carrying pack.offline draws no "through" text in the header or the body', async () => {
    withOffline = true;
    const root = await card(CARDS[2]!);
    expect(root.querySelector('.analytics-range')).not.toBeNull();
    expect(root.querySelector('.analytics-range')?.textContent).not.toContain('through');
    expect(root.querySelector('.analytics-identity')?.textContent ?? '').not.toContain('through');
    expect(root.textContent).not.toContain('studio');
  });
});

describe('what each card keeps', () => {
  test('the cost card is a number: no chart, the figure and the unpriced line stay', async () => {
    const root = await card(CARDS[1]!);
    expect(root.querySelector('[data-chart]')).toBeNull();
    expect(root.querySelector('.analytics-headline')).not.toBeNull();
    expect(root.textContent).toContain('75 unpriced observations');
  });

  test('the tokens card keeps its chart', async () => {
    expect((await card(CARDS[0]!)).querySelector('[data-chart]')).not.toBeNull();
  });

  for (const entry of CARDS.slice(2)) {
    test(`${entry.title}: no total, the rows stay`, async () => {
      const root = await card(entry);
      expect(root.querySelector('.analytics-headline')).toBeNull();
      expect(root.querySelectorAll('.analytics-ranking li').length).toBeGreaterThan(0);
    });
  }
});

describe('the default Home', () => {
  test('seeds no activity history, and the gallery still offers working time', async () => {
    localStorage.clear();
    const createChart = vi.fn(async (chart: ChartConfig) => ({ ...chart, revision: 1 }));
    vi.doMock('./api', () => ({ createChart, annotations: vi.fn(async () => []) }));
    vi.resetModules();
    const { analytics: fresh, seedHomeAnalytics } = await import('./state.svelte');
    const { createLayoutStore } = await import('../../engine/layout.svelte');
    fresh.charts = {}; fresh.error = '';
    await seedHomeAnalytics(createLayoutStore('home'));
    const seeded = createChart.mock.calls.map(([chart]) => chart.series[0]?.metric);
    expect(seeded).toHaveLength(5);
    expect(seeded).not.toContain('working_seconds');
    expect(PRESETS.some((preset) => preset.id === 'working_time' && preset.series[0]?.metric === 'working_seconds')).toBe(true);
  });
});
