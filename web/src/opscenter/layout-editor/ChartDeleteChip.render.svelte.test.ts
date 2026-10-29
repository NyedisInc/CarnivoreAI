/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const hoisted = vi.hoisted(() => ({ deleteChart: vi.fn(async () => undefined) }));
vi.mock('../cells/analytics/api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), deleteChart: hoisted.deleteChart }));

import ChartDeleteChip from './ChartDeleteChip.svelte';
import { analytics } from '../cells/analytics/state.svelte';
import { tripwires } from '../viz/tripwires.svelte';
import type { ChartConfig } from '../cells/analytics/types';
import type { Tripwire } from '../viz/tripwire-model';

let app: Record<string, unknown> | null = null;
const chip = (): HTMLButtonElement => document.querySelector('[data-chart-delete="c1"]') as HTMLButtonElement;
const press = async (): Promise<void> => { chip().click(); await tick(); flushSync(); };

beforeEach(() => {
  vi.useFakeTimers();
  hoisted.deleteChart.mockClear();
  analytics.charts = { c1: { id: 'c1', revision: 3, title: 'x' } as ChartConfig, c2: { id: 'c2', revision: 1, title: 'y' } as ChartConfig };
  tripwires.list = [];
  app = mount(ChartDeleteChip, { target: document.body, props: { chartId: 'c1' } });
});
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; vi.useRealTimers(); });

describe('delete chip', () => {
  test('the first press only arms it', async () => {
    expect(chip().textContent).toBe('delete');
    await press();
    expect(chip().textContent).toBe('delete?');
    expect(hoisted.deleteChart).not.toHaveBeenCalled();
  });

  test('the second press deletes at the chart revision and drops it from the list', async () => {
    await press();
    await press();
    await vi.waitFor(() => expect(Object.keys(analytics.charts)).toEqual(['c2']));
    expect(hoisted.deleteChart).toHaveBeenCalledWith('c1', 3);
  });

  test('the timeout, Esc and blur each cancel', async () => {
    await press();
    vi.advanceTimersByTime(4100); await tick(); flushSync();
    expect(chip().textContent).toBe('delete');
    await press();
    chip().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await tick(); flushSync();
    expect(chip().textContent).toBe('delete');
    await press();
    chip().dispatchEvent(new FocusEvent('blur')); await tick(); flushSync();
    expect(chip().textContent).toBe('delete');
    expect(hoisted.deleteChart).not.toHaveBeenCalled();
  });

  test('a chart with tripwires says so, and they leave the list with it', async () => {
    tripwires.list = [{ id: 'w1', chart_id: 'c1' }, { id: 'w2', chart_id: 'c1' }, { id: 'w3', chart_id: 'c2' }] as Tripwire[];
    await press();
    expect(chip().textContent).toBe('delete + 2 tripwires?');
    await press();
    await vi.waitFor(() => expect(tripwires.list.map((wire) => wire.id)).toEqual(['w3']));
  });
});
