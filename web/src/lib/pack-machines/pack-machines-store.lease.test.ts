import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const reads: string[] = [];
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    reads.push(path);
    return { master_install_id: 'fetched', self_install_id: 'me', settings: {}, disagreement: null, machines: [] };
  },
}));

beforeEach(() => {
  vi.useFakeTimers();
  reads.length = 0;
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
  vi.resetModules();
});
afterEach(() => {
  vi.useRealTimers();
  delete (globalThis as { localStorage?: unknown }).localStorage;
});

it('re-reads on its own when no frame and no read has come for twice the renewal interval', async () => {
  await import('./pack-machines-store.svelte');
  const { resourcePush } = await import('../../lib/resource-push/boot');
  resourcePush().store.hello({ resource_topics: ['pack_machines'] });
  await vi.advanceTimersByTimeAsync(0);
  reads.length = 0;
  await vi.advanceTimersByTimeAsync(59000);
  expect(reads.filter((p) => p === '/pack/machines')).toHaveLength(0);
  await vi.advanceTimersByTimeAsync(2000);
  expect(reads.filter((p) => p === '/pack/machines')).toHaveLength(1);
});
