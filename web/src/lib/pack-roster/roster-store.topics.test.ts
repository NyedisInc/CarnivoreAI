import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const reads: string[] = [];

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    reads.push(path);
    if (path === '/hosts') return { status: 'ok', hosts: [] };
    if (path === '/federation/discovered') return { discovered: [], state: 'on' };
    return [];
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
  const roster = await import('./roster-store.svelte');
  const { resourcePush } = await import('../../lib/resource-push/boot');
  return { roster, push: resourcePush().store };
}

describe('the roster reads', () => {
  it('run no timer read while pack_roster is announced, and one read each when a frame names it', async () => {
    const { roster, push } = await load();
    await vi.advanceTimersByTimeAsync(0);
    push.hello({ resource_topics: ['pack_roster'] });
    await vi.advanceTimersByTimeAsync(0);
    reads.length = 0;
    await vi.advanceTimersByTimeAsync(roster.ROSTER_POLL_MS * 4);
    expect(reads).toEqual([]);

    push.frame({ topics: ['pack_roster'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(reads.filter((p) => p === '/hosts')).toHaveLength(1);
    expect(reads.filter((p) => p === '/federation/peers')).toHaveLength(1);
    expect(reads.filter((p) => p === '/federation/discovered')).toHaveLength(1);
    push.frame({ topics: ['computers'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(reads).toHaveLength(3); // another topic reads nothing
  });

  it('poll on the slow timer while the server does not announce the topic', async () => {
    const { roster, push } = await load();
    push.hello({ resource_topics: [] });
    await vi.advanceTimersByTimeAsync(0);
    reads.length = 0;
    await vi.advanceTimersByTimeAsync(roster.ROSTER_POLL_MS * 2 + 100);
    expect(reads.filter((p) => p === '/hosts').length).toBeGreaterThanOrEqual(2);
  });
});
