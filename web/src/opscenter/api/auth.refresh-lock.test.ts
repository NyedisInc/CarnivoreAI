/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type AuthModule = typeof import('./auth.svelte');

function fakeLocks() {
  const tails = new Map<string, Promise<unknown>>();
  return {
    request: vi.fn(async (name: string, opts: { signal?: AbortSignal }, cb: () => Promise<unknown>) => {
      const before = tails.get(name) ?? Promise.resolve();
      const run = before.catch(() => undefined).then(async () => {
        if (opts?.signal?.aborted) throw Object.assign(new Error('aborted'), { name: 'AbortError' });
        return cb();
      });
      tails.set(name, run);
      return run;
    }),
  };
}

function fakeServer() {
  const state = { posts: 0, revoked: false, spent: new Set<string>(), live: new Set<string>(['r0']), counter: 0 };
  const fetchFn = vi.fn(async (_url: string, init: RequestInit) => {
    state.posts += 1;
    await new Promise((resolve) => setTimeout(resolve, 5));
    const sent = JSON.parse(String(init.body)).refresh_token as string;
    if (state.revoked || state.spent.has(sent) || !state.live.has(sent)) {
      state.revoked = true;
      state.live.clear();
      return new Response('{}', { status: 401 });
    }
    state.spent.add(sent);
    state.live.delete(sent);
    state.counter += 1;
    state.live.add(`r${state.counter}`);
    return new Response(JSON.stringify({ access_token: `a${state.counter}`, refresh_token: `r${state.counter}` }), { status: 200 });
  });
  return { state, fetchFn };
}

async function openWindow(): Promise<AuthModule> {
  vi.resetModules();
  return import('./auth.svelte');
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('claude_tunnel_token', 'expired');
  localStorage.setItem('claude_refresh_token', 'r0');
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('refresh across windows', () => {
  it('two windows refreshing at once post once and both keep the one token chain', async () => {
    const server = fakeServer();
    vi.stubGlobal('fetch', server.fetchFn);
    vi.stubGlobal('navigator', { ...navigator, locks: fakeLocks() });
    const one = await openWindow();
    const two = await openWindow();
    const [a, b] = await Promise.all([one.refreshTokens(), two.refreshTokens()]);
    expect([a, b]).toEqual([true, true]);
    expect(server.state.posts).toBe(1);
    expect(server.state.revoked).toBe(false);
    expect(one.auth.state).toBe('signed-in');
    expect(two.auth.state).toBe('signed-in');
    expect(localStorage.getItem('claude_refresh_token')).toBe('r1');
    expect(localStorage.getItem('claude_tunnel_token')).toBe('a1');
  });

  it('without the lock the same race spends the token twice and revokes the chain (the control: this test can go red)', async () => {
    const server = fakeServer();
    vi.stubGlobal('fetch', server.fetchFn);
    vi.stubGlobal('navigator', { ...navigator, locks: undefined });
    const one = await openWindow();
    const two = await openWindow();
    const results = await Promise.all([one.refreshTokens(), two.refreshTokens()]);
    expect(server.state.posts).toBe(2);
    expect(server.state.revoked).toBe(true);
    expect(results).toContain(false);
  });

  it('a window whose lock wait times out keeps every token and answers false', async () => {
    vi.useFakeTimers();
    const server = fakeServer();
    vi.stubGlobal('fetch', server.fetchFn);
    const held = vi.fn((_name: string, opts: { signal?: AbortSignal }) => new Promise((_resolve, reject) => {
      opts.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    }));
    vi.stubGlobal('navigator', { ...navigator, locks: { request: held } });
    const win = await openWindow();
    const pending = win.refreshTokens();
    await vi.advanceTimersByTimeAsync(20000);
    await expect(pending).resolves.toBe(false);
    expect(server.state.posts).toBe(0);
    expect(localStorage.getItem('claude_refresh_token')).toBe('r0');
    expect(localStorage.getItem('claude_tunnel_token')).toBe('expired');
  });
});
