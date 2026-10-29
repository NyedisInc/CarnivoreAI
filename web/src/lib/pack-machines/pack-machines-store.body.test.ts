import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const reads: string[] = [];
const view = (tag: string) => ({ master_install_id: tag, self_install_id: 'me', settings: {}, disagreement: null, machines: [] });

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    reads.push(path);
    return view('fetched');
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
  const store = await import('./pack-machines-store.svelte');
  const { resourcePush } = await import('../../lib/resource-push/boot');
  const push = resourcePush().store;
  push.hello({ resource_topics: ['pack_machines'] });
  await vi.advanceTimersByTimeAsync(0);
  reads.length = 0;
  return { store, push };
}

describe('a pushed body', () => {
  it('is applied with no GET, and a frame without a body falls back to one GET', async () => {
    const { store, push } = await load();
    push.frame({ topics: ['pack_machines'], bodies: { pack_machines: view('pushed') } });
    await vi.advanceTimersByTimeAsync(0);
    expect(reads).toEqual([]);
    expect(store.packMachines.data?.master_install_id).toBe('pushed');

    push.frame({ topics: ['pack_machines'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(reads).toEqual(['/pack/machines']);
    expect(store.packMachines.data?.master_install_id).toBe('fetched');
  });

  it('re-reads once the last read is older than the lease renewal, so the server lease is kept', async () => {
    const { store, push } = await load();
    await vi.advanceTimersByTimeAsync(46000);
    push.frame({ topics: ['pack_machines'], bodies: { pack_machines: view('pushed') } });
    await vi.advanceTimersByTimeAsync(0);
    expect(reads.filter((p) => p === '/pack/machines')).toHaveLength(1);
    expect(store.packMachines.data?.master_install_id).toBe('fetched');
  });
});
