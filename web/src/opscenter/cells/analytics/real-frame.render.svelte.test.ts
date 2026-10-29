/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('../../viz/query-client', () => ({ runQueries: vi.fn(async (items: { metric: string; operation: string }[]) => items.map((item) => ({ ok: true, result: {
  metric: item.metric, operation: item.operation, unit: 'tokens', resolution: 'hour',
  series: [{ key: 'all', label: 'all', points: [{ time: '2026-10-01T00:00:00Z', value: 100 }] }],
  summary: { value: 100, samples: 3, contributing_conversations: 4 },
  ranking: [{ key: 'a', label: 'Carnivore', value: 100 }, { key: 'b', label: 'Fleet', value: 50 }], coverage: { minute_rows: 9 } } }))) }));
vi.mock('../../viz/visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));

import Cell from './Cell.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import { analytics } from './state.svelte';
import { tripwires } from '../../viz/tripwires.svelte';
import type { ChartConfig } from './types';
import type { SlotId } from '../../engine/types';

let handle: Record<string, unknown> | null = null;
afterEach(() => { if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); });

async function framed(viz: string, title: string, series: Record<string, unknown>): Promise<HTMLElement> {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  analytics.charts = { c1: { id: 'c1', revision: 1, title, enabled: true, ...(viz ? { viz } : {}), series: [series], filters: {}, range: { mode: 'global' }, display: { type: 'line' } } as unknown as ChartConfig };
  tripwires.list = [];
  const target = document.createElement('div');
  document.body.append(target);
  handle = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: Cell, width: 460, height: 320 } as never });
  for (let i = 0; i < 6; i += 1) { await new Promise((resolve) => setTimeout(resolve, 60)); await tick(); }
  flushSync();
  return target;
}

describe('analytics cards with their real renderers', () => {
  test('a timeline card names itself in the host header', async () => {
    const target = await framed('', 'tokens used', { metric: 'total_tokens', operation: 'timeline' });
    expect(target.querySelector('.oc-frame-title h2')?.textContent?.trim()).toBe('tokens used');
  });
  test('a ranking card names itself in the host header and draws name, value and bar per row', async () => {
    const target = await framed('', 'tokens by project', { metric: 'total_tokens', operation: 'ranking', group_by: 'project' });
    expect(target.querySelector('.oc-frame-title h2')?.textContent?.trim()).toBe('tokens by project');
    const row = target.querySelector('.analytics-ranking > li');
    expect(row?.querySelector('.analytics-ranking-row span')?.textContent).toBe('Carnivore');
    expect(row?.querySelector('.analytics-ranking-row strong')?.textContent).toMatch(/\d/);
    expect(row?.querySelector('.analytics-ranking-track .analytics-ranking-fill')).not.toBeNull();
  });
  test('a ranking row is a block so the chart body list rule never lays its bar beside the line', () => {
    const css = readFileSync('src/opscenter/cells/analytics/TimelineView.svelte', 'utf8');
    expect(css).toMatch(/\.analytics-ranking > li \{ display: block;/);
    expect(readFileSync('src/lib/base/chart-frame.css', 'utf8')).toMatch(/\.oc-chart-frame__list > li \{\s*display: flex;/);
  });
});
