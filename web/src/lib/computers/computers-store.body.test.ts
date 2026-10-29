import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const reads: string[] = [];
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    reads.push(path);
    return { tag: 'fetched', computers: [] };
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

it('applies a pushed view with no GET, and a frame without a body falls back to one GET', async () => {
  const store = await import('./computers-store.svelte');
  const { resourcePush } = await import('../resource-push/boot');
  const push = resourcePush().store;
  push.hello({ resource_topics: ['computers', 'pack_machines'] });
  await vi.advanceTimersByTimeAsync(0);
  reads.length = 0;

  push.frame({ topics: ['computers'], bodies: { computers: { tag: 'pushed', computers: [] } } });
  await vi.advanceTimersByTimeAsync(0);
  expect(reads).toEqual([]);
  expect((store.computers.data as unknown as { tag: string }).tag).toBe('pushed');

  push.frame({ topics: ['pack_machines'] });
  await vi.advanceTimersByTimeAsync(0);
  expect(reads).toHaveLength(1);
  expect((store.computers.data as unknown as { tag: string }).tag).toBe('fetched');
});
