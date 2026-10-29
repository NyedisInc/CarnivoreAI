/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const pullBlock = vi.hoisted(() => ({ values: {} as Record<string, unknown> }));
vi.mock('../api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/auth.svelte')>()),
  authFetch: vi.fn(async () => ({ values: pullBlock.values })),
}));

import {
  HOME_LAYOUT_FIELD as FIELD,
  WRITE_DELAY,
  applyHome,
  type HomeValue,
  hydrateHome,
  parseHome,
  resetHomeSync,
  startHomeSync,
} from './home-sync.svelte';
import { homeSeedLevel, setHomeSeedLevel } from './home-seed';
import { homeLayout } from './layout.svelte';
import { resetLayout } from './model';
import { META } from './meta';
import { flushSave, STORAGE_KEYS } from './persist';
import type { Layout } from './types';

class FakePrefs {
  HYDRATED = 'hydrated';
  COMMITTED = 'committed';
  values: Record<string, unknown> = {};
  sets: Array<{ layout: Layout; boards: Array<{ id: string; name: string; layout: Layout }>; analytics_seed: number }> = [];
  theirsFirst: unknown[] = [];
  listeners: Array<(name: string, value: unknown, record: { state: string }) => void> = [];
  status(): string {
    return this.HYDRATED;
  }
  committedValue(name: string): unknown {
    return this.values[name];
  }
  async set(name: string, value: unknown): Promise<{ status: string }> {
    const sent = JSON.parse(JSON.stringify(value)) as { boards: Array<{ id: string; layout: Layout }> };
    this.sets.push({ ...sent, layout: sent.boards.find((b) => b.id === 'home')!.layout } as never);
    if (this.theirsFirst.length) {
      this.values[name] = this.theirsFirst.shift();
      return { status: 'stale_revision' };
    }
    this.values[name] = JSON.parse(JSON.stringify(value));
    return { status: 'committed' };
  }
  subscribe(listener: (name: string, value: unknown, record: { state: string }) => void): () => void {
    this.listeners.push(listener);
    return () => {};
  }
}

let prefs: FakePrefs;

function theirs(collapsed: boolean, seed = 0): HomeValue {
  return { v: 2, boards: [{ id: 'home', name: 'home', layout: { ...resetLayout(META, 'home'), heroCollapsed: collapsed } }], analytics_seed: seed };
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(WRITE_DELAY * 6);
}

function storeLocal(collapsed: boolean): void {
  homeLayout.setHeroCollapsed(collapsed);
  flushSave('home');
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  prefs = new FakePrefs();
  (globalThis as { Preferences?: unknown }).Preferences = prefs;
});

afterEach(() => {
  resetHomeSync();
  flushSave();
  localStorage.clear();
  delete (globalThis as { Preferences?: unknown }).Preferences;
  pullBlock.values = {};
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('parseHome: absent is null, a present value is read, the seed is clamped', () => {
  expect(parseHome(undefined)).toBeNull();
  expect(parseHome({ v: 1 })).toBeNull();
  expect(parseHome({ v: 1, layout: { v: 6, rows: [] }, analytics_seed: 9 })?.analytics_seed).toBe(2);
  expect(parseHome({ v: 1, layout: { v: 6, rows: [] } })?.analytics_seed).toBe(0);
});

test('first load with no server value sends this browser layout up once, with its old seeding level', async () => {
  storeLocal(!homeLayout.state.layout.heroCollapsed);
  const mine = homeLayout.state.layout.heroCollapsed;
  localStorage.setItem('cloudecode.opscenter.home-analytics.v1', 'done');
  startHomeSync({ target: null });
  await hydrateHome();
  expect(prefs.sets).toHaveLength(1);
  expect(prefs.sets[0]!.layout.heroCollapsed).toBe(mine);
  expect(prefs.sets[0]!.analytics_seed).toBe(1);
  await settle();
  expect(prefs.sets).toHaveLength(1);
  expect(homeLayout.state.layout.heroCollapsed).toBe(mine);
});

test('first load with nothing stored and nothing on the server writes nothing', async () => {
  startHomeSync({ target: null });
  await hydrateHome();
  await settle();
  expect(prefs.sets).toHaveLength(0);
});

test('a present server value is shown and never written back', async () => {
  const mine = homeLayout.state.layout.heroCollapsed;
  prefs.values[FIELD] = theirs(!mine, 2);
  startHomeSync({ target: null });
  await hydrateHome();
  expect(homeLayout.state.layout.heroCollapsed).toBe(!mine);
  expect(homeSeedLevel()).toBe(2);
  await settle();
  expect(prefs.sets).toHaveLength(0);
});

test('a user operation writes once, carrying the current layout', async () => {
  prefs.values[FIELD] = theirs(false);
  startHomeSync({ target: null });
  await hydrateHome();
  homeLayout.setHeroCollapsed(true);
  homeLayout.setHeroCollapsed(false);
  homeLayout.setHeroCollapsed(true);
  await settle();
  expect(prefs.sets).toHaveLength(1);
  expect(prefs.sets[0]!.layout.heroCollapsed).toBe(true);
});

test('409: adopts the server value, replays this layout once on it, keeps the higher seeding level, and announces', async () => {
  prefs.values[FIELD] = theirs(false);
  startHomeSync({ target: null });
  await hydrateHome();
  prefs.theirsFirst = [theirs(false, 2)];
  homeLayout.setHeroCollapsed(true);
  await settle();
  expect(prefs.sets).toHaveLength(2);
  expect(prefs.sets[1]!.layout.heroCollapsed).toBe(true);
  expect(prefs.sets[1]!.analytics_seed).toBe(2);
  expect(homeLayout.state.announcement).toContain('your change kept');
});

test('409 twice: the second loss adopts theirs as it stands, no third write', async () => {
  prefs.values[FIELD] = theirs(false);
  startHomeSync({ target: null });
  await hydrateHome();
  prefs.theirsFirst = [theirs(false), theirs(false)];
  homeLayout.setHeroCollapsed(true);
  await settle();
  expect(prefs.sets).toHaveLength(2);
  expect(homeLayout.state.layout.heroCollapsed).toBe(false);
  expect(homeLayout.state.announcement).toContain('showing theirs');
});

test('migration 409: another browser migrated first and theirs is adopted', async () => {
  storeLocal(!homeLayout.state.layout.heroCollapsed);
  const mine = homeLayout.state.layout.heroCollapsed;
  prefs.theirsFirst = [theirs(!mine, 1)];
  startHomeSync({ target: null });
  await hydrateHome();
  expect(prefs.sets).toHaveLength(1);
  expect(homeLayout.state.layout.heroCollapsed).toBe(!mine);
  expect(homeSeedLevel()).toBe(1);
});

test('a remote change waits for a running gesture', async () => {
  const pointer = await import('./pointer');
  const active = vi.spyOn(pointer, 'gestureActive').mockReturnValue(true);
  const mine = homeLayout.state.layout.heroCollapsed;
  prefs.values[FIELD] = theirs(mine);
  startHomeSync({ target: null });
  await hydrateHome();
  applyHome(theirs(!mine));
  expect(homeLayout.state.layout.heroCollapsed).toBe(mine);
  active.mockReturnValue(false);
  await settle();
  expect(homeLayout.state.layout.heroCollapsed).toBe(!mine);
  expect(prefs.sets).toHaveLength(0);
});

test('the seeding level is written with the layout and the server value wins for a second browser', async () => {
  prefs.values[FIELD] = theirs(false, 0);
  startHomeSync({ target: null });
  await hydrateHome();
  setHomeSeedLevel(2);
  await settle();
  expect(prefs.sets).toHaveLength(1);
  expect(prefs.sets[0]!.analytics_seed).toBe(2);
  resetHomeSync();
  localStorage.clear();
  startHomeSync({ target: null });
  await hydrateHome();
  expect(homeSeedLevel()).toBe(2);
});

test('the pop-out follows the server layout and never writes', async () => {
  const mine = homeLayout.state.layout.heroCollapsed;
  pullBlock.values = { [FIELD]: theirs(!mine, 1) };
  startHomeSync({ popout: true, target: null });
  await vi.advanceTimersByTimeAsync(10);
  expect(homeLayout.state.layout.heroCollapsed).toBe(!mine);
  homeLayout.setHeroCollapsed(mine);
  setHomeSeedLevel(2);
  await settle();
  expect(prefs.sets).toHaveLength(0);
  expect(localStorage.getItem(STORAGE_KEYS.home)).not.toBeNull();
});

test('a phone fold (title-bar tap) is saved to the server on the tap, in the home layout', async () => {
  prefs.values[FIELD] = theirs(false);
  startHomeSync({ target: null });
  await hydrateHome();
  const was = homeLayout.isCollapsed('themes');
  homeLayout.toggleCollapsed('themes');
  await settle();
  expect(prefs.sets).toHaveLength(1);
  expect(prefs.sets[0]!.layout.collapsed.includes('themes')).toBe(!was);
  homeLayout.toggleCollapsed('themes');
  await settle();
  expect(prefs.sets).toHaveLength(2);
  expect(prefs.sets[1]!.layout.collapsed.includes('themes')).toBe(was);
});
