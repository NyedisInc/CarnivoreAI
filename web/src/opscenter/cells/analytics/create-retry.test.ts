import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../../api/auth.svelte', () => ({ authFetch: vi.fn(), ApiError: class extends Error { status = 0; } }));

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test('the write after a failed create is a POST of the whole chart', async () => {
  const { authFetch } = await import('../../api/auth.svelte');
  const { addChart, saveChartView, analytics } = await import('./state.svelte');
  vi.mocked(authFetch).mockReset();
  vi.mocked(authFetch).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ revision: 3 } as never);
  const chart = addChart();
  await vi.advanceTimersByTimeAsync(0);
  expect(analytics.error).not.toBe('');
  saveChartView(chart.id, (c) => ({ ...c, title: 'renamed' }));
  await vi.advanceTimersByTimeAsync(1000);
  const calls = vi.mocked(authFetch).mock.calls;
  expect(calls).toHaveLength(2);
  expect(calls[1]![0]).toBe('/stats/charts');
  expect(calls[1]![1]?.method).toBe('POST');
  expect(JSON.parse(String(calls[1]![1]?.body)).title).toBe('renamed');
});
