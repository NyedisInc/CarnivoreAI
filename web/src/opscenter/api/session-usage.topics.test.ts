/* frame, and the */
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
      return new Response(JSON.stringify({ total_tokens: 1 }), {
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
  delete (globalThis as { ListingPush?: unknown }).ListingPush;
});

function listRow(id: string, family: string): void {
  (globalThis as { ListingPush?: unknown }).ListingPush = {
    rows: () => [{ activity_status: 'idle', agent_family: family, session: { id } }],
  };
}

const count = () => reads.filter((u) => u.endsWith('/sessions/ses_1/token-usage')).length;

describe('session usage', () => {
  it('arms no timer while live, re-reads on its own frame only, polls when the socket is down', async () => {
    const { resourcePush } = await import('../../lib/resource-push/boot');
    const store = resourcePush().store;
    const mod = await import('./session-usage.svelte');
    listRow('ses_1', 'claude');
    mod.sessionUsage('ses_1');
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(1);

    store.hello({ resource_topics: ['session_usage', 'provider_ledger'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(2); // the resync read on hello

    await vi.advanceTimersByTimeAsync(20 * mod.SESSION_USAGE_POLL_MS);
    expect(count()).toBe(2); // twenty polling periods, nothing timed

    store.frame({ topics: ['session_usage:ses_2'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(2); // another session's frame is not ours

    store.frame({ topics: ['session_usage:ses_1'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(3);

    store.closed();
    await vi.advanceTimersByTimeAsync(mod.SESSION_USAGE_POLL_MS + 1);
    expect(count()).toBeGreaterThanOrEqual(4); // down: the fallback poll is back
    mod.releaseSessionUsage('ses_1');
  });

  it.each([
    ['a codex row', 'ses_1', 'codex'],
    ['a remote row', 'remote:peer-x:ses_1', 'claude'],
    ['a row the listing does not carry', 'ses_1', ''],
  ])('keeps its timer armed for %s even when the topics are live', async (_name, id, family) => {
    if (family) listRow(id, family);
    const { resourcePush } = await import('../../lib/resource-push/boot');
    const mod = await import('./session-usage.svelte');
    mod.sessionUsage(id);
    await vi.advanceTimersByTimeAsync(0);
    resourcePush().store.hello({ resource_topics: ['session_usage', 'provider_ledger'] });
    await vi.advanceTimersByTimeAsync(0);
    const before = reads.length;
    await vi.advanceTimersByTimeAsync(mod.SESSION_USAGE_POLL_MS + 1);
    expect(reads.length).toBeGreaterThan(before);
    mod.releaseSessionUsage(id);
  });
});
