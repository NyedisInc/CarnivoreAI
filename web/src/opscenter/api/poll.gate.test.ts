import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const ACCESS_KEY = 'claude_tunnel_token';
const REFRESH_KEY = 'claude_refresh_token';

function fakeStorage(seed: Record<string, string> = {}) {
  const map = new Map(Object.entries(seed));
  return {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
}

async function load(seed: Record<string, string> = {}) {
  const store = fakeStorage(seed);
  (globalThis as { localStorage?: unknown }).localStorage = store;
  vi.resetModules();
  const poll = await import('./poll.svelte');
  const auth = await import('./auth.svelte');
  return { store, poll, auth };
}

describe('the poll gate re-reads storage on the host handoff', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (globalThis as { localStorage?: unknown }).localStorage;
  });

  it('starts the probe when the app signs in after the bundle loaded signed out', async () => {
    const { store, poll, auth } = await load();

    expect(auth.auth.state).toBe('signed-out');

    const fetcher = vi.fn(async () => 'rows');
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'test' });

    expect(fetcher).not.toHaveBeenCalled();
    expect(probe.status).toBe('signed-out');

    store.setItem(ACCESS_KEY, 'an-access-token');
    store.setItem(REFRESH_KEY, 'a-refresh-token');
    expect(probe.status).toBe('signed-out');

    poll.restartAll();
    await vi.runOnlyPendingTimersAsync();

    expect(auth.auth.state).toBe('signed-in');
    expect(fetcher).toHaveBeenCalled();
    expect(probe.status).toBe('ok');
    expect(probe.data).toBe('rows');
  });

  it('returns to the placeholder when the app signs out', async () => {
    const { store, poll, auth } = await load({
      [ACCESS_KEY]: 'an-access-token',
      [REFRESH_KEY]: 'a-refresh-token',
    });

    expect(auth.auth.state).toBe('signed-in');

    const fetcher = vi.fn(async () => 'rows');
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'test' });
    await vi.runOnlyPendingTimersAsync();
    expect(probe.status).toBe('ok');

    store.removeItem(ACCESS_KEY);
    store.removeItem(REFRESH_KEY);
    poll.pauseAll();

    expect(auth.auth.state).toBe('signed-out');
    expect(probe.status).toBe('signed-out');

    const before = fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20000);
    expect(fetcher.mock.calls.length).toBe(before);
  });

  it('a pause for the terminal screen keeps the rows, because the user is still signed in', async () => {
    const { poll } = await load({
      [ACCESS_KEY]: 'an-access-token',
      [REFRESH_KEY]: 'a-refresh-token',
    });

    const fetcher = vi.fn(async () => 'rows');
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'test' });
    await vi.runOnlyPendingTimersAsync();
    expect(probe.status).toBe('ok');

    poll.pauseAll();
    expect(probe.status).toBe('ok');
    expect(probe.data).toBe('rows');
  });
  it('explicit refresh reads a paused resource once but respects signout and disposal', async () => {
    const { poll, store } = await load({ [ACCESS_KEY]: 'an-access-token' });
    const fetcher = vi.fn(async () => 'rows');
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'explicit' });
    await vi.runOnlyPendingTimersAsync();
    poll.pauseAll();
    const before = fetcher.mock.calls.length;
    await probe.refresh();
    expect(fetcher.mock.calls.length).toBe(before);
    await probe.refresh(true);
    expect(fetcher.mock.calls.length).toBe(before + 1);
    await vi.advanceTimersByTimeAsync(20000);
    expect(fetcher.mock.calls.length).toBe(before + 1);
    store.removeItem(ACCESS_KEY);
    poll.pauseAll();
    await probe.refresh(true);
    expect(fetcher.mock.calls.length).toBe(before + 1);
    store.setItem(ACCESS_KEY, 'an-access-token');
    poll.pauseAll();
    probe.stop();
    await probe.refresh(true);
    expect(fetcher.mock.calls.length).toBe(before + 1);
  });

});
