/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount, type Component } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const runQueries = vi.fn();
vi.mock('../../viz/query-client', () => ({ runQueries: (...args: unknown[]) => runQueries(...args) }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('./api', () => ({ annotations: vi.fn(async () => []) }));
vi.mock('./ChartCanvas.svelte', () => ({ default: () => {} }));

import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import AnalyticsCell from './Cell.svelte';
import { analytics } from './state.svelte';
import { tripwires } from '../../viz/tripwires.svelte';
import type { SlotId } from '../../engine/types';
import type { CellProps } from '../../lib/cell';
import { UNION_MIN, vizFloor } from '../../viz/specs';
import type { ChartConfig, QueryResult } from './types';

const rankingCard = { series: [{ metric: 'total_tokens', operation: 'ranking', group_by: 'model' }] } as ChartConfig;

const NANO = 1_000_000_000;
const ranking = [
  { key: 'opus', label: 'claude-opus', value: 900 * NANO }, { key: 'sonnet', label: 'claude-sonnet', value: 300 * NANO },
  { key: 'haiku', label: 'claude-haiku', value: 90 * NANO }, { key: 'codex', label: 'gpt-codex', value: 20 * NANO },
  { key: 'misc', label: 'misc-model', value: 5 * NANO }, { key: 'x', label: 'sixth', value: NANO },
];

function answer(metric: string, operation: string): QueryResult {
  const base = { metric, operation: operation as QueryResult['operation'], unit: metric === 'estimated_cost_nano_usd' ? 'nano_usd' : 'tokens', resolution: 'hour' as QueryResult['resolution'],
    series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value: 5 }] }], summary: { value: 1200 * NANO, samples: 3 },
    ranking: operation === 'ranking' ? ranking : [], coverage: { minute_rows: 9 } };
  return (operation === 'comparison' ? { ...base, comparison: { range: { from: 'a', to: 'b' }, series: [], summary: { value: 1000 * NANO, samples: 3 } } } : base) as QueryResult;
}

let app: Record<string, unknown> | null = null;
beforeEach(() => {
  tripwires.list = [];
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; runQueries.mockReset(); vi.unstubAllGlobals(); });

async function card(title: string, series: ChartConfig['series'], height: number, width?: number): Promise<HTMLElement> {
  analytics.charts = { c1: { id: 'c1', revision: 1, title, enabled: true, series, filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as ChartConfig };
  runQueries.mockImplementation(async (items: { metric: string; operation: string }[]) => items.map((item) => ({ ok: true, result: answer(item.metric, item.operation) })));
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: AnalyticsCell as unknown as Component<CellProps>, height, ...(width ? { width } : {}) } as never });
  for (let i = 0; i < 10; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
  return target;
}

describe('the lowest row the divider allows', () => {
  test('a compact card draws in the body the lowest row leaves under its title row', () => {
    const titleRowPx = 36;
    expect(vizFloor(rankingCard).height).toBeLessThanOrEqual(UNION_MIN.height - titleRowPx);
  });
});

describe('a card below the old floor', () => {
  test('a ranking card at 100px draws its list and its own name, never the plate', async () => {
    const root = await card('tokens by model', [{ metric: 'total_tokens', operation: 'ranking', group_by: 'model' }], 100);
    expect(root.querySelector('[data-widget-unavailable]')).toBeNull();
    expect(root.querySelectorAll('.analytics-ranking li').length).toBeGreaterThan(0);
    expect(root.querySelector('[data-widget-head]')?.textContent).toContain('tokens by model');
  });

  test('a chart card at 100px degrades to its compact form: no plate, its own name, its headline figure', async () => {
    const root = await card('tokens used', [{ metric: 'total_tokens', operation: 'timeline' }], 100);
    expect(root.querySelector('[data-widget-unavailable]')).toBeNull();
    const head = root.querySelector('[data-widget-head]')?.textContent ?? '';
    expect(head).toContain('tokens used');
    expect(head.toLowerCase()).not.toContain('analytics');
    expect(root.querySelector('.analytics-headline')).not.toBeNull();
  });

  test('a chart card narrower than its renderer floor never draws the plate', async () => {
    const root = await card('tokens used', [{ metric: 'total_tokens', operation: 'timeline' }], 300, 170);
    expect(root.querySelector('[data-widget-unavailable]')).toBeNull();
    expect(root.querySelector('.analytics-headline')).not.toBeNull();
  });

  test('the tokens breakdown is kept whole or dropped whole: a narrow card keeps title, figure and caption only', async () => {
    vi.stubGlobal('ResizeObserver', class { constructor(private cb: () => void) {} observe() { this.cb(); } unobserve() {} disconnect() {} });
    const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
    const tall = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 180 });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 76 });
    try {
      const root = await card('tokens used', [{ metric: 'total_tokens', operation: 'timeline' }], 300, 180);
      expect(root.querySelector('.analytics-facts--corner')).toBeNull();
      expect(root.querySelector('.analytics-headline strong')).not.toBeNull();
    } finally {
      if (width) Object.defineProperty(HTMLElement.prototype, 'clientWidth', width); else delete (HTMLElement.prototype as unknown as Record<string, unknown>)['clientWidth'];
      if (tall) Object.defineProperty(HTMLElement.prototype, 'clientHeight', tall); else delete (HTMLElement.prototype as unknown as Record<string, unknown>)['clientHeight'];
    }
  });
});

describe('the estimated cost card', () => {
  const COST: ChartConfig['series'] = [{ metric: 'estimated_cost_nano_usd', operation: 'timeline' }];

  test('lists its top models by cost, the change against the window before, and the hourly average', async () => {
    const root = await card('estimated cost', COST, 400);
    const rows = [...root.querySelectorAll('.analytics-ranking li')].map((row) => row.textContent ?? '');
    expect(rows).toHaveLength(5);
    expect(rows[0]).toContain('claude-opus');
    expect(rows[0]).toContain('$900');
    const line = root.querySelector('.analytics-change')?.textContent ?? '';
    expect(line).toContain('up 20% vs prior 24h');
    expect(line).toContain('$50/h avg');
  });

  test('asks for the model ranking and the prior-window comparison', async () => {
    await card('estimated cost', COST, 400);
    const asked = (runQueries.mock.calls[0]![0] as { operation: string; group_by?: string }[]).map((item) => `${item.operation}:${item.group_by ?? ''}`);
    expect(asked).toContain('ranking:model');
    expect(asked).toContain('comparison:');
  });

  test('at 100px it keeps the figure and drops to fewer rows, never the plate', async () => {
    const root = await card('estimated cost', COST, 100);
    expect(root.querySelector('[data-widget-unavailable]')).toBeNull();
    expect(root.querySelector('.analytics-headline')).not.toBeNull();
  });
});
