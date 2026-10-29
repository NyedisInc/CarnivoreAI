/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const authFetch = vi.fn();
vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: () => {},
  authFetch: (...args: unknown[]) => authFetch(...args),
  ApiError: class ApiError extends Error { status = 0; },
}));
const handlers = new Map<string, Set<(frame: unknown) => void>>();
vi.mock('../../api/events.svelte', () => ({
  subscribe: (kind: string, handler: (frame: unknown) => void) => {
    const held = handlers.get(kind) ?? new Set();
    held.add(handler);
    handlers.set(kind, held);
    return () => held.delete(handler);
  },
}));

const CHART = {
  id: 'c1', revision: 1, title: 'tokens', enabled: true, series: [{ metric: 'total_tokens' }], filters: {},
  range: { mode: 'global' }, display: { type: 'line' },
};
const liveReads = (): number => authFetch.mock.calls.filter((call) => call[0] === '/stats/live').length;

describe('GET /stats/live has one reader per tab', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('VisibilityObserver', class { observe(): void {} disconnect(): void {} });
    authFetch.mockReset();
    authFetch.mockImplementation(async (path: string) => {
      if (path === '/stats/charts') return [CHART];
      if (path === '/stats/catalog') return [];
      if (path === '/stats/settings') return { enabled: true, revision: 1 };
      if (path.startsWith('/stats/dimensions')) return { items: [] };
      if (path === '/stats/live') return { state: 'ok', metrics: { running_sessions: 2 }, burn: {} };
      return {};
    });
  });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); handlers.clear(); });

  test.each(['Controls', 'TimelineView'])('%s alone starts the shared live read (each card watches by itself)', async (name) => {
    const { analytics } = await import('./state.svelte');
    analytics.charts.c1 = CHART as never;
    const Card = (await import(`./${name}.svelte`)).default;
    const props = name === 'TimelineView' ? { instance: 'analytics:c1', tier: 'full' as never } : {};
    const card = mount(Card, { target: document.body, props });
    flushSync();
    await vi.advanceTimersByTimeAsync(0);
    expect(liveReads()).toBe(1);
    await unmount(card);
    authFetch.mockClear();
    for (const handler of handlers.get('stats.changed') ?? []) handler({ type: 'stats.changed', changed: { live: true } });
    await vi.advanceTimersByTimeAsync(20_000);
    expect(liveReads()).toBe(0);
  });

  test('Controls and a TimelineView, both mounted, share ONE read; a live frame costs one; a full refresh none', async () => {
    const { analytics, applyStatsChanged, refreshAnalytics } = await import('./state.svelte');
    const { live } = await import('../../viz/noc-feed.svelte');
    const Controls = (await import('./Controls.svelte')).default;
    const TimelineView = (await import('./TimelineView.svelte')).default;
    analytics.charts.c1 = CHART as never;
    const controls = mount(Controls, { target: document.body });
    const card = mount(TimelineView, { target: document.body, props: { instance: 'analytics:c1', tier: 'full' as never } });
    flushSync();
    await vi.advanceTimersByTimeAsync(0);
    expect(liveReads()).toBe(1);
    expect(live.data?.metrics?.running_sessions).toBe(2);

    await vi.advanceTimersByTimeAsync(16_000);
    authFetch.mockClear();
    await refreshAnalytics();
    expect(liveReads()).toBe(0);

    const changed = { metrics: ['total_tokens'], live: true, events: false, dimensions: false };
    for (const handler of handlers.get('stats.changed') ?? []) handler({ type: 'stats.changed', changed });
    await applyStatsChanged(changed);
    await vi.advanceTimersByTimeAsync(0);
    expect(liveReads()).toBe(1);
    await unmount(card);
    await unmount(controls);
  }, 30_000);
});
