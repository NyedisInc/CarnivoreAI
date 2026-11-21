import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let reads: string[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  reads = [];
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      reads.push(url);
      return new Response(JSON.stringify({ accounts: {}, tracks_master: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }),
  );
  vi.resetModules();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (globalThis as { localStorage?: unknown }).localStorage;
  delete (globalThis as { ResourcePush?: unknown }).ResourcePush;
});

const count = (suffix: string) => reads.filter((u) => u.endsWith(suffix)).length;

describe('the relay panel stores', () => {
  it('packRelay: no timer while pack_relay is live, one read per frame, poll back when the socket drops', async () => {
    const { resourcePush } = await import('../resource-push/boot');
    const store = resourcePush().store;
    const mod = await import('./pack-relay-store.svelte');
    mod.packRelay.refresh(true);
    await vi.advanceTimersByTimeAsync(0);
    store.hello({ resource_topics: ['pack_relay', 'pack_machines', 'computers', 'provider_ledger'] });
    await vi.advanceTimersByTimeAsync(0);
    const base = count('/pack/relay');
    await vi.advanceTimersByTimeAsync(20 * mod.PACK_RELAY_POLL_MS);
    expect(count('/pack/relay')).toBe(base); // twenty polling periods, nothing timed
    store.frame({ topics: ['pack_relay'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count('/pack/relay')).toBe(base + 1);
    for (const [i, topic] of ['pack_machines', 'computers', 'provider_ledger'].entries()) {
      store.frame({ topics: [topic] });
      await vi.advanceTimersByTimeAsync(0);
      expect(count('/pack/relay')).toBe(base + 2 + i);
    }
    store.closed();
    await vi.advanceTimersByTimeAsync(mod.PACK_RELAY_POLL_MS + 1);
    expect(count('/pack/relay')).toBeGreaterThan(base + 4);
  });

  it('tracksMaster follows pack_tracks_master and claudeAccounts follows provider_ledger', async () => {
    const { resourcePush } = await import('../resource-push/boot');
    const store = resourcePush().store;
    const relay = await import('./pack-relay-store.svelte');
    const machines = await import('./pack-machines-store.svelte');
    relay.claudeAccounts.refresh(true);
    machines.tracksMaster.refresh(true);
    await vi.advanceTimersByTimeAsync(0);
    store.hello({ resource_topics: ['provider_ledger', 'pack_tracks_master', 'pack_relay'] });
    await vi.advanceTimersByTimeAsync(0);
    const tracks = count('/pack/tracks-master');
    const accounts = count('/provider-ledger/accounts');
    await vi.advanceTimersByTimeAsync(10 * 60000);
    expect(reads.filter((u) => u.endsWith('/pack/tracks-master')).length).toBe(tracks);
    expect(count('/provider-ledger/accounts')).toBe(accounts);
    store.frame({ topics: ['pack_tracks_master'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count('/pack/tracks-master')).toBe(tracks + 1);
  });

  it('the themes store re-reads on a themes frame (a catalog install announces it)', async () => {
    const { resourcePush } = await import('../resource-push/boot');
    const store = resourcePush().store;
    const mod = await import('../../opscenter/api/themes.svelte');
    mod.themes.refresh(true);
    await vi.advanceTimersByTimeAsync(0);
    store.hello({ resource_topics: ['themes'] });
    await vi.advanceTimersByTimeAsync(0);
    const base = count('/themes');
    store.frame({ topics: ['themes'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count('/themes')).toBe(base + 1);
  });
});
