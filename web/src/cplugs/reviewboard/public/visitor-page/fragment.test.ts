/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LINK_HEADER, forgetLinkSecret, takeLinkSecret } from './fragment';
import { fetchBoard } from './board-client';

const TOKEN = `pbl_${'A'.repeat(22)}.${'b'.repeat(43)}`;

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.history.replaceState(null, '', `/?x=1#${TOKEN}`);
});
afterEach(() => vi.restoreAllMocks());

describe('takeLinkSecret', () => {
  it('reads the secret from the fragment and strips it from the address bar', () => {
    expect(takeLinkSecret(window)).toBe(TOKEN);
    expect(window.location.hash).toBe('');
    expect(window.location.href).not.toContain(TOKEN);
    expect(window.location.pathname + window.location.search).toBe('/?x=1');
  });

  it('strips with replaceState, so the secret is not left in history either', () => {
    const spy = vi.spyOn(window.history, 'replaceState');
    takeLinkSecret(window);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(String(spy.mock.calls[0]![2])).not.toContain(TOKEN);
  });

  it('keeps the secret for this tab only: a reload without the fragment still has it, and localStorage never does', () => {
    takeLinkSecret(window);
    expect(takeLinkSecret(window)).toBe(TOKEN);
    expect(window.localStorage.length).toBe(0);
    expect(Object.keys(window.localStorage)).toEqual([]);
    expect(JSON.stringify(Object.entries(window.localStorage))).not.toContain(TOKEN);
  });

  it('answers null when there is no fragment and nothing kept', () => {
    window.history.replaceState(null, '', '/');
    expect(takeLinkSecret(window)).toBeNull();
  });

  it('a malformed escape in the fragment is no secret, and the fragment is still stripped', () => {
    window.history.replaceState(null, '', '/#%E0%A4%A');
    expect(takeLinkSecret(window)).toBeNull();
    expect(window.location.hash).toBe('');
  });

  it('survives a sessionStorage that throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(takeLinkSecret(window)).toBe(TOKEN);
  });
});

describe('forgetLinkSecret', () => {
  it('removes what this tab kept, so a reload does not ask again with a link that is dead', () => {
    takeLinkSecret(window);
    expect(window.sessionStorage.getItem('publicboard.link')).toBe(TOKEN);
    forgetLinkSecret(window);
    expect(window.sessionStorage.getItem('publicboard.link')).toBeNull();
    expect(takeLinkSecret(window)).toBeNull();
  });
  it('survives a sessionStorage that throws', () => {
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(() => forgetLinkSecret(window)).not.toThrow();
  });
});

describe('fetchBoard sends the secret as the header and nowhere else', () => {
  it('puts it in Carnivore-Board-Link, with no query, no cookie, no referrer', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ title: 't', revision: 'r1', views: [{ id: 'main', label: 'main', frame: '/f/x' }] }), { status: 200 }));
    await fetchBoard(TOKEN, fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [url, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/board');
    expect(url).not.toContain(TOKEN);
    expect((init.headers as Record<string, string>)[LINK_HEADER]).toBe(TOKEN);
    expect(LINK_HEADER).toBe('Carnivore-Board-Link');
    expect(init.credentials).toBe('omit');
    expect(init.referrerPolicy).toBe('no-referrer');
    expect(init.cache).toBe('no-store');
    expect(Object.keys(init.headers as object)).toEqual([LINK_HEADER]);
  });

  it('with no secret asks nothing and says not found', async () => {
    const fetcher = vi.fn();
    expect(await fetchBoard(null, fetcher)).toEqual({ kind: 'state', state: 'invalid' });
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('fetchBoard maps every answer to a state', () => {
  const answer = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }));
  it.each([
    [404, 'invalid'], [404, 'ended'], [429, 'limited'], [400, 'misrouted'], [503, 'unavailable'],
  ])('%i %s', async (status, state) => {
    expect(await fetchBoard(TOKEN, answer(status, { state }))).toEqual({ kind: 'state', state });
  });
  it('an unknown state or a body that is not JSON names no verdict about the link: unavailable, never a crash (`proxy-refusal.test.ts`)', async () => {
    expect(await fetchBoard(TOKEN, answer(404, { state: 'banana' }))).toEqual({ kind: 'state', state: 'unavailable' });
    expect(await fetchBoard(TOKEN, vi.fn(async () => new Response('<html>', { status: 404 })))).toEqual({ kind: 'state', state: 'unavailable' });
    expect(await fetchBoard(TOKEN, vi.fn(async () => new Response('<html>', { status: 502 })))).toEqual({ kind: 'state', state: 'unavailable' });
  });
  it('a network failure is unavailable', async () => {
    expect(await fetchBoard(TOKEN, vi.fn(async () => { throw new TypeError('network'); }))).toEqual({ kind: 'state', state: 'unavailable' });
  });
  it('a 200 that is not a board is unavailable', async () => {
    expect(await fetchBoard(TOKEN, answer(200, { nope: 1 }))).toEqual({ kind: 'state', state: 'unavailable' });
  });
});
