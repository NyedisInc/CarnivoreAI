/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error {}, auth: { state: 'signed-in' } }));
vi.mock('../../viz/tripwire-follow', () => ({ followTripwires: () => {} }));
vi.mock('../../viz/query-client', () => ({ runQueries: vi.fn(async () => []) }));

import Cell from './Cell.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import { analytics } from './state.svelte';
import { readChartTitle, rememberChartTitle, resetChartTitles } from './chart-titles';
import { tripwires } from '../../viz/tripwires.svelte';
import type { SlotId } from '../../engine/types';

let handle: Record<string, unknown> | null = null;
beforeEach(() => {
  localStorage.clear();
  resetChartTitles();
  analytics.charts = {};
  analytics.loaded = false;
  analytics.error = '';
  tripwires.list = [];
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { if (handle) unmount(handle); handle = null; document.body.innerHTML = ''; vi.unstubAllGlobals(); analytics.loaded = false; analytics.error = ''; });

async function pending(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  handle = mount(CellInFrame, { target, props: { slot: 'analytics:c1' as SlotId, cell: Cell, width: 300, height: 260 } as never });
  for (let i = 0; i < 4; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
  return target;
}

describe('a card with no definition yet', () => {
  test('names itself from the remembered title and shows the loading state, not "unavailable"', async () => {
    rememberChartTitle('c1', 'tokens by project');
    const target = await pending();
    expect(target.querySelector('.oc-frame-title h2')?.textContent).toBe('tokens by project');
    expect(target.querySelector('.oc-state')?.getAttribute('data-state')).toBe('loading');
    expect(target.textContent).not.toContain('chart definition unavailable');
  });

  test('says unavailable only once the list has landed without this chart', async () => {
    analytics.loaded = true;
    const target = await pending();
    expect(target.querySelector('.oc-state')?.getAttribute('data-state')).toBe('empty');
    expect(target.textContent).toContain('chart definition unavailable');
  });

  test('a failed read is an error state with a retry', async () => {
    analytics.error = 'offline';
    const target = await pending();
    expect(target.querySelector('.oc-state')?.getAttribute('data-state')).toBe('error');
    expect(target.querySelector('.oc-state button')).not.toBeNull();
  });
});

describe('the remembered titles', () => {
  test('survive a reload and are read back by chart id', () => {
    rememberChartTitle('a', 'tokens used');
    resetChartTitles();
    expect(readChartTitle('a')).toBe('tokens used');
    expect(readChartTitle('missing')).toBeNull();
  });

  test('a broken store is a blank header, never a throw', () => {
    localStorage.setItem('carnivore.analytics.titles', '{not json');
    resetChartTitles();
    expect(readChartTitle('a')).toBeNull();
  });
});
