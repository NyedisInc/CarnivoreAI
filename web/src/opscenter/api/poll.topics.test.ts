import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function signedInStorage() {
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  return {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  (globalThis as { localStorage?: unknown }).localStorage = signedInStorage();
  vi.resetModules();
});

afterEach(() => {
  vi.useRealTimers();
  delete (globalThis as { localStorage?: unknown }).localStorage;
  delete (globalThis as { ResourcePush?: unknown }).ResourcePush;
});

async function load() {
  const poll = await import('./poll.svelte');
  const { resourcePush } = await import('../../lib/resource-push/boot');
  return { poll, store: resourcePush().store };
}

describe('a resource that answers a pushed topic', () => {
  it('re-reads on its topic and on a hello, never on another topic, and arms no timer while live', async () => {
    const { poll, store } = await load();
    const fetcher = vi.fn<() => Promise<string>>().mockResolvedValue('v');
    const res = poll.resource(fetcher, { intervalMs: 5000, name: 'layouts', topics: ['layouts'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);

    store.hello({ resource_topics: ['layouts', 'toasts'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(poll.listPollers().map((p) => p.name)).not.toContain('layouts');

    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetcher).toHaveBeenCalledTimes(2);

    store.frame({ topics: ['toasts'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);

    store.frame({ topics: ['toasts', 'layouts'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(3);
    res.stop();
  });

  it('polls only while the socket is down or the server does not announce the topic', async () => {
    const { poll, store } = await load();
    const fetcher = vi.fn<() => Promise<string>>().mockResolvedValue('v');
    const res = poll.resource(fetcher, { intervalMs: 5000, name: 'browsers', topics: ['browsers'] });
    await vi.advanceTimersByTimeAsync(0);

    store.hello({ resource_topics: [] });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetcher).toHaveBeenCalledTimes(3);

    store.hello({ resource_topics: ['browsers'] });
    await vi.advanceTimersByTimeAsync(0);
    const afterHello = fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetcher).toHaveBeenCalledTimes(afterHello);

    store.closed();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetcher).toHaveBeenCalledTimes(afterHello + 2);
    res.stop();
  });

  it('a paused resource reads on its topic but not on a hello', async () => {
    const { poll, store } = await load();
    const fetcher = vi.fn<() => Promise<string>>().mockResolvedValue('v');
    const res = poll.resource(fetcher, { intervalMs: 5000, name: 'projects', topics: ['projects'] });
    await vi.advanceTimersByTimeAsync(0);
    store.hello({ resource_topics: ['projects'] });
    await vi.advanceTimersByTimeAsync(0);
    poll.pauseAll();
    const before = fetcher.mock.calls.length;
    store.hello({ resource_topics: ['projects'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(before);
    store.frame({ topics: ['projects'] });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(before + 1);
    res.stop();
  });
});

describe('pushOrPoll, the hand-written pollers\' shape', () => {
  it('runs the interval only while a topic is not live and refreshes on its frames', async () => {
    const { ResourceTopicStore, pushOrPoll } = await import('../../lib/resource-push/store');
    const store = new ResourceTopicStore();
    const refresh = vi.fn();
    const stop = pushOrPoll(store, refresh, 10_000, ['toasts']);
    await vi.advanceTimersByTimeAsync(20_000);
    expect(refresh).toHaveBeenCalledTimes(2);
    store.hello({ resource_topics: ['toasts'] });
    expect(refresh).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(60_000);
    store.frame({ topics: ['layouts'] });
    expect(refresh).toHaveBeenCalledTimes(3);
    store.frame({ topics: ['toasts'] });
    expect(refresh).toHaveBeenCalledTimes(4);
    store.closed();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(refresh).toHaveBeenCalledTimes(5);
    stop();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(refresh).toHaveBeenCalledTimes(5);
  });
});

describe('pollWhile, a timer that runs only while there is something moving', () => {
  it('holds the timer off while the listing is live and the gate is shut, and a refresh re-arms it', async () => {
    const listeners = new Set<(names: string[]) => void>();
    (globalThis as { ListingPush?: unknown }).ListingPush = {
      isLive: () => true,
      onChange: (fn: (names: string[]) => void) => { listeners.add(fn); return () => listeners.delete(fn); },
    };
    try {
      const { poll } = await load();
      let moving = false;
      const fetcher = vi.fn<() => Promise<string>>().mockResolvedValue('v');
      const res = poll.resource(fetcher, { intervalMs: 5000, name: 'usage', pollWhile: () => moving });
      await vi.advanceTimersByTimeAsync(30_000);
      expect(fetcher).toHaveBeenCalledTimes(1);

      moving = true;
      await res.refresh();
      await vi.advanceTimersByTimeAsync(10_000);
      expect(fetcher).toHaveBeenCalledTimes(4);

      moving = false;
      await vi.advanceTimersByTimeAsync(30_000);
      expect(fetcher).toHaveBeenCalledTimes(5);
      res.stop();
    } finally {
      delete (globalThis as { ListingPush?: unknown }).ListingPush;
    }
  });
});
