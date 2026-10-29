/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const authFetch = vi.fn();
vi.mock('../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: () => {},
  authFetch: (...args: unknown[]) => authFetch(...args),
  ApiError: class ApiError extends Error { status = 0; },
}));
const handlers = new Map<string, Set<(frame: unknown) => void>>();
vi.mock('../api/events.svelte', () => ({
  subscribe: (kind: string, handler: (frame: unknown) => void) => {
    const held = handlers.get(kind) ?? new Set();
    held.add(handler);
    handlers.set(kind, held);
    return () => held.delete(handler);
  },
}));

let hidden = false;
const liveReads = (): number => authFetch.mock.calls.filter((call) => call[0] === '/stats/live').length;
const frame = (): void => {
  for (const handler of handlers.get('stats.changed') ?? []) handler({ type: 'stats.changed', changed: { live: true, events: false } });
};
const setHidden = (value: boolean): void => {
  hidden = value;
  document.dispatchEvent(new Event('visibilitychange'));
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-11T12:00:00Z'));
  hidden = false;
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hidden ? 'hidden' : 'visible') });
  authFetch.mockReset();
  authFetch.mockResolvedValue({ state: 'ok', metrics: {}, burn: {} });
});
afterEach(() => { vi.useRealTimers(); handlers.clear(); });

test('a burst of frames inside the 15 s floor costs one deferred read, never one each', async () => {
  const { watchLive, FEED_MIN_MS } = await import('./noc-feed.svelte');
  const release = watchLive();
  await vi.advanceTimersByTimeAsync(0);
  expect(liveReads()).toBe(1);
  for (let i = 0; i < 20; i += 1) frame();
  await vi.advanceTimersByTimeAsync(FEED_MIN_MS - 1000);
  expect(liveReads()).toBe(1);
  await vi.advanceTimersByTimeAsync(1500);
  expect(liveReads()).toBe(2);
  await vi.advanceTimersByTimeAsync(FEED_MIN_MS * 2);
  expect(liveReads()).toBe(2);
  release();
});

test('a frame that lands during a read is read once when that read finishes (u165-02)', async () => {
  const { watchTicker, FEED_MIN_MS } = await import('./noc-feed.svelte');
  let finish: (value: unknown) => void = () => undefined;
  authFetch.mockImplementation((path: string) => (path.startsWith('/stats/event-log') ? new Promise((resolve) => (finish = resolve)) : Promise.resolve({ items: [] })));
  const release = watchTicker();
  await vi.advanceTimersByTimeAsync(0);
  const reads = (): number => authFetch.mock.calls.filter((call) => String(call[0]).startsWith('/stats/event-log')).length;
  expect(reads()).toBe(1);
  for (const handler of handlers.get('stats.tripwire') ?? []) handler({ type: 'stats.tripwire' });
  finish({ items: [] });
  await vi.advanceTimersByTimeAsync(FEED_MIN_MS + 1000);
  expect(reads()).toBe(2);
  release();
});

test('a hidden tab reads nothing; the missed frame is read once when it returns', async () => {
  const { watchLive, FEED_MIN_MS } = await import('./noc-feed.svelte');
  const release = watchLive();
  await vi.advanceTimersByTimeAsync(FEED_MIN_MS * 2);
  const before = liveReads();
  setHidden(true);
  frame();
  frame();
  await vi.advanceTimersByTimeAsync(FEED_MIN_MS * 3);
  expect(liveReads()).toBe(before);
  setHidden(false);
  await vi.advanceTimersByTimeAsync(0);
  expect(liveReads()).toBe(before + 1);
  release();
});
