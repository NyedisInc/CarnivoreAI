/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('../../viz/query-client', () => ({ runQueries: vi.fn(async () => []) }));
vi.mock('../../viz/registry', () => ({ VIZ_REGISTRY: new Proxy({}, { get: () => ({ component: ($$anchor: Comment) => { const mark = document.createElement('i'); mark.dataset.chart = ''; $$anchor.before(mark); } }) }) }));

import Cell from './Cell.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import { analytics } from './state.svelte';
import { resetChartTitles } from './chart-titles';
import { tripwires } from '../../viz/tripwires.svelte';
import type { ChartConfig } from './types';
import type { SlotId } from '../../engine/types';

let handle: Record<string, unknown> | null = null;
beforeEach(() => { localStorage.clear(); resetChartTitles(); });
afterEach(() => { if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); });

async function framed(width: number, height: number): Promise<HTMLElement> {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  analytics.charts = { c1: { id: 'c1', revision: 1, title: 'tokens by hour', enabled: true, viz: 'kpi', series: [{ metric: 'total_tokens', operation: 'summary' }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as unknown as ChartConfig };
  tripwires.list = [];
  const target = document.createElement('div');
  document.body.append(target);
  handle = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: Cell, width, height } as never });
  for (let i = 0; i < 4; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
  return target;
}

describe('the analytics card header', () => {
  test('a drawn chart names itself in the header', async () => {
    const target = await framed(400, 300);
    expect(target.querySelector('[data-chart]')).not.toBeNull();
    expect(target.querySelector('.oc-frame-title h2')?.textContent).toBe('tokens by hour');
  });
  test('a chart below its renderer floor is held in its box (no plate) and still names itself in the header', async () => {
    const target = await framed(100, 50);
    expect(target.querySelector('[data-widget-unavailable]')).toBeNull();
    expect(target.querySelector('.alarm-frame__body--clipped [data-chart]')).not.toBeNull();
    expect(target.querySelector('.oc-frame-title h2')?.textContent).toBe('tokens by hour');
  });
  test('before the chart list has loaded the header never reads the kind word, then names the chart', async () => {
    vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
    analytics.charts = {};
    tripwires.list = [];
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: Cell, width: 400, height: 300 } as never });
    for (let i = 0; i < 4; i += 1) { await tick(); await Promise.resolve(); }
    flushSync();
    expect(target.querySelector('.oc-frame-title h2')?.textContent?.trim()).not.toBe('analytics');
    expect(target.querySelector('.oc-frame-title h2')?.textContent?.trim()).toBe('');
    expect(target.querySelector('[aria-label*="analytics"]')).not.toBeNull();
    analytics.charts = { c1: { id: 'c1', revision: 1, title: 'tokens by hour', enabled: true, viz: 'kpi', series: [{ metric: 'total_tokens', operation: 'summary' }], filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as unknown as ChartConfig };
    for (let i = 0; i < 4; i += 1) { await tick(); await Promise.resolve(); }
    flushSync();
    expect(target.querySelector('.oc-frame-title h2')?.textContent).toBe('tokens by hour');
  });
});
