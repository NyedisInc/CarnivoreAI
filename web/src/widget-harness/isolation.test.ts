/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const REAL_TOKEN = 'a-real-looking-token-that-must-never-be-touched';
const KEY = 'claude_tunnel_token';

let realStorage: Storage;

beforeEach(() => {
  vi.resetModules();
  realStorage = globalThis.localStorage;
  realStorage.clear();
  realStorage.setItem(KEY, REAL_TOKEN);
  realStorage.setItem('claude_tunnel_refresh', 'real-refresh');
});

afterEach(() => {
  realStorage.clear();
});

describe('boot.ts isolation', () => {
  it('stores only its placeholder, in memory, and never reads the app token', async () => {
    await import('./boot');
    expect(globalThis.localStorage).not.toBe(realStorage);
    expect(globalThis.localStorage.getItem(KEY)).toBe('widget-harness-placeholder');
    expect(globalThis.localStorage.getItem('claude_tunnel_refresh')).toBeNull();
    expect(globalThis.localStorage.length).toBe(1);
  });

  it('leaves the real storage exactly as it was, even after the page writes and clears its own', async () => {
    await import('./boot');
    globalThis.localStorage.setItem(KEY, 'rotated');
    globalThis.localStorage.clear();
    globalThis.sessionStorage.setItem('x', 'y');
    expect(realStorage.getItem(KEY)).toBe(REAL_TOKEN);
    expect(realStorage.getItem('claude_tunnel_refresh')).toBe('real-refresh');
    expect(realStorage.length).toBe(2);
  });

  it('answers every /api/ request from the fixture and never from the network', async () => {
    const network = vi.fn(async () => new Response('{}'));
    globalThis.fetch = network as unknown as typeof fetch;
    const boot = await import('./boot');
    boot.serveFixture({ 'GET /ping': { pong: true } });
    const answered = await fetch('/api/v1/ping');
    expect(await answered.json()).toEqual({ pong: true });
    const write = await fetch('/api/v1/preferences', { method: 'PUT', body: '{"a":1}' });
    expect(write.status).toBe(404);
    expect(network).not.toHaveBeenCalled();
  });
});
