import { beforeEach, expect, test, vi } from 'vitest';

const api = vi.hoisted(() => ({
  fetchPresets: vi.fn(), fetchConfig: vi.fn(), fetchFeatures: vi.fn(), fetchLedgerAccounts: vi.fn(), fetchModels: vi.fn(),
}));
vi.mock('./api', () => api);
vi.mock('../../opscenter/api/events.svelte', () => ({ startEvents: vi.fn(), subscribe: vi.fn(() => () => {}) }));

import { ai, refresh } from './store.svelte';

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.fetchPresets.mockResolvedValue([]);
  api.fetchFeatures.mockResolvedValue([]);
  api.fetchLedgerAccounts.mockResolvedValue([]);
});

test('a refresh during a read triggers one trailing read and ends on the newest revision', async () => {
  let release!: (v: unknown) => void;
  api.fetchConfig.mockImplementationOnce(() => new Promise((r) => (release = r))).mockResolvedValue({ revision: 2 });
  const first = refresh();
  const second = refresh();
  const third = refresh();
  release({ revision: 1 });
  await Promise.all([first, second, third]);
  expect(api.fetchConfig).toHaveBeenCalledTimes(2);
  expect((ai.config as unknown as { revision: number }).revision).toBe(2);
});

test('refreshes with nothing running read once each', async () => {
  api.fetchConfig.mockResolvedValue({ revision: 1 });
  await refresh();
  await refresh();
  expect(api.fetchConfig).toHaveBeenCalledTimes(2);
});
