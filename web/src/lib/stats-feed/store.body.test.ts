import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const reads: string[] = [];
const doc = (rev: number, now: number) => ({ rev, now, state: 'ok' });
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    reads.push(path);
    return doc(1, 1);
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

async function load() {
  const store = await import('./store.svelte');
  const { resourcePush } = await import('../resource-push/boot');
  const push = resourcePush().store;
  push.hello({ resource_topics: ['stats_feed'] });
  const release = store.acquireStatsFeed('1h');
  await vi.advanceTimersByTimeAsync(0);
  reads.length = 0;
  return { store, push, release };
}

it('applies a pushed document with no GET, reads on a body-less keepalive, and re-reads when the frames stop', async () => {
  const { store, push } = await load();
  push.frame({ topics: ['stats_feed'], bodies: { stats_feed: { '1h': doc(5, 50) } } });
  await vi.advanceTimersByTimeAsync(0);
  expect(reads).toEqual([]);
  expect(store.statsFeed('1h')?.data?.rev).toBe(5);

  push.frame({ topics: ['stats_feed'] });
  await vi.advanceTimersByTimeAsync(0);
  expect(reads).toHaveLength(1);

  reads.length = 0;
  await vi.advanceTimersByTimeAsync(31000);
  expect(reads).toHaveLength(1);
});
