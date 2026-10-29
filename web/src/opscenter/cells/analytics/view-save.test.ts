import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { ChartConfig } from './types';

const authFetch = vi.fn();
vi.mock('../../api/auth.svelte', () => ({
  authFetch: (...args: unknown[]) => authFetch(...args),
  ApiError: class ApiError extends Error { status = 0; },
}));

const chart: ChartConfig = { id: 'c1', revision: 3, title: 'usage', enabled: true, series: [{ metric: 'total_tokens' }],
  filters: {}, range: { mode: 'global' }, display: { type: 'line', legend: true } };

function serve(): void {
  authFetch.mockImplementation(async (path: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'PATCH' && path.startsWith('/stats/charts/')) {
      const sent = JSON.parse(init.body!) as ChartConfig;
      return { ...sent, revision: sent.revision + 1 };
    }
    if (path === '/stats/charts') return [chart];
    if (path === '/stats/catalog') return [];
    if (path === '/stats/settings') return { enabled: true, revision: 1 };
    if (path.startsWith('/stats/dimensions')) return { items: [] };
    return { state: 'ok' };
  });
}

const patches = (): unknown[][] => authFetch.mock.calls.filter((call) => (call[1] as { method?: string } | undefined)?.method === 'PATCH');

describe('widget settings write only on a user action', () => {
  beforeEach(() => { vi.useFakeTimers(); authFetch.mockReset(); serve(); });
  afterEach(() => { vi.useRealTimers(); });

  test('a data refresh never writes; a user change writes once, debounced, with the new settings', async () => {
    const { analytics, refreshAnalytics, saveChartView } = await import('./state.svelte');
    await refreshAnalytics();
    await vi.advanceTimersByTimeAsync(5000);
    expect(patches()).toHaveLength(0);
    expect(analytics.charts.c1?.revision).toBe(3);

    saveChartView('c1', (c) => ({ ...c, resolution: 'hour' }));
    saveChartView('c1', (c) => ({ ...c, display: { ...c.display, hidden_series: ['total tokens'] } }));
    await refreshAnalytics();
    expect(patches()).toHaveLength(0);
    expect(analytics.charts.c1?.resolution).toBe('hour');

    await vi.advanceTimersByTimeAsync(1000);
    expect(patches()).toHaveLength(1);
    const body = JSON.parse((patches()[0]![1] as { body: string }).body) as ChartConfig;
    expect(body.resolution).toBe('hour');
    expect(body.display.hidden_series).toEqual(['total tokens']);
    expect(analytics.charts.c1?.revision).toBe(4);

    await refreshAnalytics();
    await vi.advanceTimersByTimeAsync(5000);
    expect(patches()).toHaveLength(1);
  });
});
