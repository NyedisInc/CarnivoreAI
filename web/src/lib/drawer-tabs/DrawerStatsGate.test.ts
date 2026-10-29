/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: string[] = [];
vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (p: string) => {
    calls.push(p);
    return { v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1, now: 2, state: 'ok', in: [1], out: [1], totals: null, rate: null, sources: [] };
  },
}));

import DrawerStatsGate from './DrawerStatsGate.svelte';
import { setDrawerEnv } from '../drawer/env';
import { setViewClassSource } from '../drawer/view-class';
import { init, setStatsShown, statsShown, PREFERENCE_FIELD, MOBILE_PREFERENCE_FIELD } from '../drawer/stats-visibility.svelte';
import { statsFeed } from '../stats-feed/store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

function bridge(store: Record<string, unknown>, writes: Array<[string, unknown]>) {
  return {
    PreferenceBridge: {
      read: (field: string, fallback: () => unknown) => (field in store ? store[field] : fallback()),
      write: vi.fn(async (field: string, value: unknown, local: () => void) => { writes.push([field, value]); store[field] = value; local(); }),
    },
  };
}

let target: HTMLElement;
const mounted: ReturnType<typeof mount>[] = [];
let observers = 0;
let timers = 0;

beforeEach(() => {
  localStorage.clear();
  calls.length = 0;
  observers = 0;
  timers = 0;
  target = document.createElement('div');
  document.body.appendChild(target);
  class FakeObserver {
    private readonly cb: (entries: Array<{ isIntersecting: boolean }>) => void;
    constructor(cb: (entries: Array<{ isIntersecting: boolean }>) => void = () => {}) { observers += 1; this.cb = cb; }
    observe(): void { this.cb([{ isIntersecting: true }]); }
    disconnect(): void { observers -= 1; }
  }
  vi.stubGlobal('VisibilityObserver', FakeObserver);
  vi.stubGlobal('ResizeObserver', FakeObserver);
  setViewClassSource(() => 'desktop');
});
afterEach(async () => {
  for (const m of mounted.splice(0)) await unmount(m);
  document.body.replaceChildren();
  setDrawerEnv(null);
  setViewClassSource(null);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i += 1) {
    await tick();
    flushSync();
    await new Promise((r) => setTimeout(r, 5));
  }
}

test('hidden mounts nothing: no markup, no observer, no timer, no feed read, no feed hold', async () => {
  setDrawerEnv(bridge({ [PREFERENCE_FIELD]: false }, []));
  init();
  const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout');
  const addSpy = vi.spyOn(document, 'addEventListener');
  mounted.push(mount(DrawerStatsGate, { target }));
  await settle();
  timers = setTimeoutSpy.mock.calls.filter(([, ms]) => typeof ms === 'number' && ms >= 1000).length;
  expect(statsShown()).toBe(false);
  expect(target.innerHTML.replace(/<!--.*?-->/g, '').trim()).toBe('');
  expect(observers).toBe(0);
  expect(timers).toBe(0);
  expect(addSpy.mock.calls.some(([type]) => type === 'visibilitychange')).toBe(false);
  expect(calls).toEqual([]);
  expect(statsFeed('1h')).toBeNull();
});

test('nothing is mounted before the choice has been read', async () => {
  mounted.push(mount(DrawerStatsGate, { target }));
  await settle();
  expect(target.querySelector('.dst-row')).toBeNull();
  expect(observers).toBe(0);
});

test('hidden by default; shown, flipping it off releases the feed and the observers at once', async () => {
  setDrawerEnv(bridge({}, []));
  init();
  mounted.push(mount(DrawerStatsGate, { target }));
  await settle();
  expect(statsShown()).toBe(false);
  expect(target.querySelector('.dst-row')).toBeNull();

  expect(setStatsShown(true)).toBe(true);
  await settle();
  expect(target.querySelector('.dst-row')).not.toBeNull();
  expect(calls).toEqual(['/stats/feed?window=1h']);
  expect(statsFeed('1h')).not.toBeNull();

  expect(setStatsShown(false)).toBe(true);
  await settle();
  expect(target.querySelector('.dst-row')).toBeNull();
  expect(statsFeed('1h')).toBeNull();
  expect(observers).toBe(0);
});

test('the desktop writes sidebar_show_stats, the phone its own field, and a stored phone choice wins without a write', async () => {
  const writes: Array<[string, unknown]> = [];
  setDrawerEnv(bridge({}, writes));
  init();
  expect(setStatsShown(true)).toBe(true);
  setViewClassSource(() => 'mobile');
  init();
  expect(statsShown()).toBe(true);
  expect(setStatsShown(false)).toBe(true);
  expect(writes).toEqual([[PREFERENCE_FIELD, true], [MOBILE_PREFERENCE_FIELD, false]]);
  setViewClassSource(() => 'desktop');
  init();
  expect(statsShown()).toBe(true);
  setViewClassSource(() => 'mobile');
  init();
  expect(statsShown()).toBe(false);
  expect(writes.length).toBe(2);
});

test('without the bridge the choice round-trips through this browser\'s own copy', () => {
  init();
  expect(setStatsShown(true)).toBe(true);
  expect(localStorage.getItem('carnivore.session.sidebar.stats')).toBe('1');
  init();
  expect(statsShown()).toBe(true);
});
