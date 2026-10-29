import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const BODY = { index: { serial: 1, stale: false }, items: [], untrusted: [] };

let calls: Array<{ method: string; url: string }> = [];

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? 'GET', url });
      return new Response(JSON.stringify(BODY), { status: 200, headers: { 'Content-Type': 'application/json' } });
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

const listReads = () => calls.filter((c) => c.method === 'GET' && c.url.endsWith('/catalog/items')).length;

describe('the catalog resource', () => {
  it('arms no timer while the catalog topic is live, re-reads on its frame, polls when the socket is down', async () => {
    const { resourcePush } = await import('../../lib/resource-push/boot');
    const store = resourcePush().store;
    const mod = await import('./catalog.svelte');
    const poll = await import('./poll.svelte');
    await vi.advanceTimersByTimeAsync(0);
    expect(listReads()).toBe(1);

    store.hello({ resource_topics: ['catalog'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(listReads()).toBe(2); // the resync read
    expect(poll.listPollers().map((p) => p.name)).not.toContain('catalog');

    await vi.advanceTimersByTimeAsync(10 * mod.CATALOG_POLL_MS);
    expect(listReads()).toBe(2);

    store.frame({ topics: ['catalog'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(listReads()).toBe(3);

    store.closed();
    await vi.advanceTimersByTimeAsync(mod.CATALOG_POLL_MS + 1);
    expect(listReads()).toBeGreaterThanOrEqual(4); // down: the fallback poll is back
    mod.catalog.stop();
  });

  it('refreshCatalogOnOpen is one POST to /catalog/refresh and reads nothing else', async () => {
    const mod = await import('./catalog.svelte');
    mod.catalog.stop();
    calls = [];
    await mod.refreshCatalogOnOpen();
    expect(calls).toEqual([{ method: 'POST', url: '/api/v1/catalog/refresh' }]);
  });
});
