import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.fn();
vi.mock('./auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./auth.svelte')>()),
  authFetch: (...args: unknown[]) => authFetch(...args),
}));

import { listingRows } from './poll.svelte';

const ROWS = [{ session: { id: 'ses_a' }, tmux_session: 'a' }];

describe('listingRows', () => {
  beforeEach(() => authFetch.mockReset());
  afterEach(() => { delete (globalThis as { ListingPush?: unknown }).ListingPush; });

  it('does not fetch while ListingPush is live', async () => {
    (globalThis as { ListingPush?: unknown }).ListingPush = { rows: () => structuredClone(ROWS) };
    expect(await listingRows('list', '/sessions/list')).toEqual(ROWS);
    expect(authFetch).not.toHaveBeenCalled();
  });

  it('shares one route read among concurrent readers while the push is down, each with its own copy', async () => {
    (globalThis as { ListingPush?: unknown }).ListingPush = { rows: () => null };
    let release!: () => void;
    authFetch.mockImplementation(() => new Promise((resolve) => { release = () => resolve(structuredClone(ROWS)); }));
    const readers = [listingRows<{ tmux_session: string }>('list', '/sessions/list'),
      listingRows<{ tmux_session: string }>('list', '/sessions/list'),
      listingRows<{ tmux_session: string }>('list', '/sessions/list')];
    release();
    const [a, b] = (await Promise.all(readers)) as [{ tmux_session: string }[], { tmux_session: string }[]];
    expect(authFetch).toHaveBeenCalledTimes(1);
    a[0]!.tmux_session = 'mutated';
    expect(b[0]!.tmux_session).toBe('a');
    authFetch.mockResolvedValue(structuredClone(ROWS));
    await listingRows('list', '/sessions/list');
    expect(authFetch).toHaveBeenCalledTimes(2);
  });
});
