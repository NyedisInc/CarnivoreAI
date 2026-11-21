import { afterEach, beforeEach, expect, test, vi } from 'vitest';

let reads: string[] = [];
let answer = 404;

beforeEach(() => {
  vi.useFakeTimers();
  reads = [];
  answer = 404;
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
      const body = answer === 200 ? { total_tokens: 1 } : { detail: 'No session with that id' };
      return new Response(JSON.stringify(body), { status: answer, headers: { 'Content-Type': 'application/json' } });
    }),
  );
  vi.resetModules();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (globalThis as { localStorage?: unknown }).localStorage;
});

const readsOf = (id: string): number => reads.filter((u) => u.endsWith(`/sessions/${id}/token-usage`)).length;

test('a row slot tail never reaches the route, on any tick', async () => {
  const mod = await import('./session-usage.svelte');
  const usage = mod.sessionUsage('row:7');
  await vi.advanceTimersByTimeAsync(mod.SESSION_USAGE_POLL_MS * 4);
  expect(reads).toEqual([]);
  expect(usage.data).toBeNull();
  mod.releaseSessionUsage('row:7');
});

test('a 404 stops the poll for that id; a refresh asks once more', async () => {
  const mod = await import('./session-usage.svelte');
  const usage = mod.sessionUsage('ses_gone');
  await vi.advanceTimersByTimeAsync(0);
  expect(readsOf('ses_gone')).toBe(1);
  expect(usage.status).toBe('unavailable');
  await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
  expect(readsOf('ses_gone')).toBe(1);
  answer = 200;
  await usage.refresh();
  expect(readsOf('ses_gone')).toBe(2);
  expect(usage.status).toBe('ok');
  await vi.advanceTimersByTimeAsync(mod.SESSION_USAGE_POLL_MS);
  expect(readsOf('ses_gone')).toBe(3);
  mod.releaseSessionUsage('ses_gone');
});
