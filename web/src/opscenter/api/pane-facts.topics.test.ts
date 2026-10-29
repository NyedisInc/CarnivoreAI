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
      return new Response(JSON.stringify({ cwd: '/r', command: 'zsh' }), {
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

const count = () => reads.filter((u) => u.endsWith('/sessions/ses_1/pane-facts')).length;

describe('pane facts', () => {
  it('arms no timer while live, re-reads on its own frame only, polls when the socket is down', async () => {
    const { resourcePush } = await import('../../lib/resource-push/boot');
    const store = resourcePush().store;
    const mod = await import('./pane-facts.svelte');
    mod.paneFacts('ses_1');
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(1);

    store.hello({ resource_topics: ['pane_facts'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(2);

    await vi.advanceTimersByTimeAsync(20 * mod.PANE_FACTS_POLL_MS);
    expect(count()).toBe(2);

    store.frame({ topics: ['pane_facts:ses_2'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(2);

    store.frame({ topics: ['pane_facts:ses_1'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(count()).toBe(3);

    store.closed();
    await vi.advanceTimersByTimeAsync(mod.PANE_FACTS_POLL_MS + 1);
    expect(count()).toBeGreaterThanOrEqual(4); // down: the fallback poll is back
    mod.releasePaneFacts('ses_1');
  });
});
