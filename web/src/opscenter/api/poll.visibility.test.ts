import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** A localStorage that holds a token, so the auth gate reads signed in. */
function signedInStorage() {
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  return {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
}

function fakeDocument(hidden: boolean) {
  const listeners = new Set<() => void>();
  return {
    hidden,
    addEventListener: (_type: string, fn: () => void): void => void listeners.add(fn),
    removeEventListener: (_type: string, fn: () => void): void => void listeners.delete(fn),
    show(): void {
      this.hidden = false;
      for (const fn of listeners) fn();
    },
  };
}

async function load(hidden: boolean) {
  const doc = fakeDocument(hidden);
  (globalThis as { localStorage?: unknown }).localStorage = signedInStorage();
  (globalThis as { document?: unknown }).document = doc;
  vi.resetModules();
  const poll = await import('./poll.svelte');
  return { doc, poll };
}

describe('a resource built in a hidden tab', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (globalThis as { localStorage?: unknown }).localStorage;
    delete (globalThis as { document?: unknown }).document;
  });

  it('still takes its first read, so the card leaves loading', async () => {
    const { poll } = await load(true);
    const fetcher = vi.fn(async () => 'rows');
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'test' });

    await vi.advanceTimersByTimeAsync(0);

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(probe.status).toBe('ok');
    expect(probe.data).toBe('rows');
    probe.stop();
  });

  it('takes its first read on a restart after a pause, still hidden', async () => {
    const { poll } = await load(true);
    const fetcher = vi.fn(async () => 'rows');
    // the home screen
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'test' });
    poll.pauseAll();
    fetcher.mockClear();
    poll.restartAll();
    await vi.advanceTimersByTimeAsync(0);
    expect(probe.status).toBe('ok');
    probe.stop();
  });

  it('does not keep polling while hidden once it holds an answer', async () => {
    const { doc, poll } = await load(true);
    const fetcher = vi.fn(async () => 'rows');
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'test' });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(30000);
    expect(fetcher).toHaveBeenCalledTimes(1);

    doc.show();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
    probe.stop();
  });
});
