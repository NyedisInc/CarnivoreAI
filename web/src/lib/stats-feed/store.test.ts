/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

const calls: string[] = [];
let next: unknown = null;
vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (p: string) => {
    calls.push(p);
    return next;
  },
}));

import { acquireStatsFeed, isFresher, statsFeed } from './store.svelte';

const b = (rev: number, now: number) => ({ v: 1, rev, now, state: 'ok' }) as never;
const settle = async (): Promise<void> => { for (let i = 0; i < 20; i += 1) await new Promise((r) => setTimeout(r, 5)); };

afterEach(() => {
  calls.length = 0;
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
});

test('the first holder starts the read, a second shares it, the last release stops it', async () => {
  next = b(1, 100);
  expect(statsFeed('1h')).toBeNull();
  const r1 = acquireStatsFeed('1h');
  const r2 = acquireStatsFeed('1h');
  await settle();
  expect(calls.filter((x) => x === '/stats/feed?window=1h')).toHaveLength(1);
  expect(statsFeed('1h')).not.toBeNull();
  r1();
  expect(statsFeed('1h')).not.toBeNull();
  r2();
  expect(statsFeed('1h')).toBeNull();
});

test('a hidden tab makes no request once it holds a value, and becoming visible reads once', async () => {
  next = b(1, 100);
  const release = acquireStatsFeed('5h');
  await settle();
  const before = calls.length;
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  await statsFeed('5h')!.refresh(true);
  expect(calls.length).toBe(before);
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  document.dispatchEvent(new Event('visibilitychange'));
  await settle();
  expect(calls.length).toBe(before + 1);
  release();
});

test('an older body is ignored', async () => {
  next = b(5, 500);
  const release = acquireStatsFeed('1d');
  await settle();
  next = b(4, 400);
  await statsFeed('1d')!.refresh(true);
  expect((statsFeed('1d')!.data as unknown as { rev: number }).rev).toBe(5);
  expect(isFresher(b(5, 500), b(4, 400))).toBe(false);
  expect(isFresher(b(5, 500), b(6, 400))).toBe(true);
  release();
});
