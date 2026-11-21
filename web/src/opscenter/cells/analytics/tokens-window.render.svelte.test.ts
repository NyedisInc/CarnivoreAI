/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('../../viz/query-client', () => ({ runQueries: vi.fn(async () => []) }));
vi.mock('../../viz/visible', () => ({ watchVisible: (_node: Element, set: (value: boolean) => void) => { set(true); return () => {}; } }));
const changed = vi.fn();
vi.mock('../../layout-editor/editor.svelte', async (original) => ({ ...(await original<object>()), changeAnalyticsConfig: (next: unknown) => changed(next) }));

import Cell from './Cell.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import { analytics } from './state.svelte';
import { tripwires } from '../../viz/tripwires.svelte';
import type { ChartConfig } from './types';
import type { SlotId } from '../../engine/types';

let handle: Record<string, unknown> | null = null;
afterEach(() => { if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); changed.mockClear(); });

async function mounted(range: ChartConfig['range']): Promise<HTMLElement> {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  analytics.charts = { c1: { id: 'c1', revision: 1, title: 'token history', enabled: true, series: [{ metric: 'total_tokens', operation: 'timeline' }], filters: {}, range, display: { type: 'line' } } as unknown as ChartConfig };
  tripwires.list = [];
  const target = document.createElement('div');
  document.body.append(target);
  handle = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: Cell, width: 460, height: 320 } as never });
  for (let i = 0; i < 6; i += 1) { await new Promise((resolve) => setTimeout(resolve, 30)); await tick(); }
  flushSync();
  return target;
}

describe('the tokens card window picker', () => {
  test('offers exactly 1h, 24h and 1w, 24h picked by default', async () => {
    const target = await mounted({ mode: 'global' });
    const options = [...target.querySelectorAll<HTMLElement>('[data-tokens-window] [data-window]')];
    expect(options.map((option) => option.dataset.window)).toEqual(['1h', '24h', '7d']);
    expect(options.find((option) => option.getAttribute('aria-checked') === 'true')?.dataset.window).toBe('24h');
  });
  test('choosing 1w saves the preset on the chart range', async () => {
    const target = await mounted({ mode: 'global' });
    target.querySelector<HTMLElement>('[data-tokens-window] [data-window="7d"]')!.click();
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ range: { mode: 'global', preset: '7d', zoom: null } }));
  });
});
