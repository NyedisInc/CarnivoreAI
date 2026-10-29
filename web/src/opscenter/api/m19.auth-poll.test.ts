/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('claude_tunnel_token', 'stale-access');
  localStorage.setItem('claude_refresh_token', 'r0');
  vi.resetModules();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('u155-03 unreachable refresh', () => {
  it('keeps the stale access token and the refresh token', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('network down'); }));
    const auth = await import('./auth.svelte');
    expect(await auth.refreshTokens()).toBe(false);
    expect(auth.auth.state).toBe('unreachable');
    expect(localStorage.getItem('claude_tunnel_token')).toBe('stale-access');
    expect(localStorage.getItem('claude_refresh_token')).toBe('r0');
    expect(auth.decideBootState(auth.hasAccessToken(), auth.hasRefreshToken())).toBe('signed-in');
  });
});

describe('u155-05 signed-out drops rows', () => {
  it('pauseAll after a sign out clears data and fetchedAt', async () => {
    vi.useFakeTimers();
    const poll = await import('./poll.svelte');
    const probe = poll.resource(async () => 'prior-user-rows', { intervalMs: 5000, name: 'm19' });
    await vi.runOnlyPendingTimersAsync();
    expect(probe.data).toBe('prior-user-rows');
    localStorage.removeItem('claude_tunnel_token');
    localStorage.removeItem('claude_refresh_token');
    poll.pauseAll();
    expect(probe.status).toBe('signed-out');
    expect(probe.data).toBeNull();
    expect(probe.fetchedAt).toBeNull();
  });
});

describe('u155-02 newSession(project) makes the bare selectProject call', () => {
  it('passes no second argument, so the host offers the launch picker', async () => {
    const selectProject = vi.fn(async () => undefined);
    vi.stubGlobal('CloudeWeb', { launchpad: { selectProject } });
    const host = await import('./host');
    expect(host.newSession({ id: 4, name: 'api' })).toBe(true);
    expect(selectProject).toHaveBeenCalledTimes(1);
    expect(selectProject.mock.calls[0]).toHaveLength(1);
  });
});
