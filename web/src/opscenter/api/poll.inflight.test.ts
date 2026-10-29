import { afterEach, describe, expect, it, vi } from 'vitest';

/** A localStorage that holds a token, so the auth gate reads signed in. */
function signedInStorage() {
  const map = new Map<string, string>([['claude_tunnel_token', 'an-access-token']]);
  return {
    getItem: (k: string): string | null => map.get(k) ?? null,
    setItem: (k: string, v: string): void => void map.set(k, v),
    removeItem: (k: string): void => void map.delete(k),
  };
}

afterEach(() => {
  delete (globalThis as { localStorage?: unknown }).localStorage;
  delete (globalThis as { ListingPush?: unknown }).ListingPush;
});

describe('a pushed resource whose read is already in flight', () => {
  it('reads again after the in-flight read, so the newer state is what it keeps', async () => {
    (globalThis as { localStorage?: unknown }).localStorage = signedInStorage();
    let notify: (names: string[]) => void = () => {};
    (globalThis as { ListingPush?: unknown }).ListingPush = {
      isLive: () => true,
      onChange: (fn: (names: string[]) => void) => { notify = fn; return () => {}; },
    };
    vi.resetModules();
    const poll = await import('./poll.svelte');

    let release: (v: string) => void = () => {};
    const slow = new Promise<string>((resolve) => { release = resolve; });
    const fetcher = vi.fn<() => Promise<string>>()
      .mockReturnValueOnce(slow)
      .mockResolvedValue('shell');
    const probe = poll.resource(fetcher, { intervalMs: 5000, name: 'test', pushed: ['list'] });
    await Promise.resolve();
    expect(fetcher).toHaveBeenCalledTimes(1);

    notify(['list']);
    release('no-family');
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(probe.data).toBe('shell'));
    probe.stop();
  });
});

describe('a pushed resource created before the listing push boots', () => {
  it('still follows a delta once the push is live (a row field)', async () => {
    (globalThis as { localStorage?: unknown }).localStorage = signedInStorage();
    const row = (state: string) => ({ session: { id: 's1' }, activity_status: state });
    const snapshot = { stream: 'a', seq: 1, collections: { list: { rows: [row('idle')], ok: true, status: null, detail: null, meta: {} } } };
    (globalThis as { API?: unknown }).API = { call: async () => snapshot };
    vi.resetModules();
    const poll = await import('./poll.svelte');
    const probe = poll.resource(
      async () => (poll.pushedRows<{ activity_status: string }>('list') ?? [])[0]?.activity_status ?? 'none',
      { intervalMs: 5000, name: 'early', pushed: ['list'] },
    );
    await vi.waitFor(() => expect(probe.data).toBe('none'));
    const boot = await import('../../lib/listing-push/boot');
    const push = boot.bootListingPush();
    await push.store.hello();
    await vi.waitFor(() => expect(probe.data).toBe('idle'));

    push.store.frame({ type: 'listing.delta', stream: 'a', seq: 2, changes: { list: { upsert: [{ key: 's1', fields: { activity_status: 'working' } }] } } });
    await vi.waitFor(() => expect(probe.data).toBe('working'));
    probe.stop();
    delete (globalThis as { API?: unknown }).API;
  });
});
