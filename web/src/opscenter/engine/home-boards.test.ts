/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/auth.svelte')>()),
  authFetch: vi.fn(async () => ({ values: {} })),
}));

import {
  HOME_LAYOUT_FIELD as FIELD,
  WRITE_DELAY,
  homeBoards,
  hydrateHome,
  parseHome,
  resetHomeSync,
  startHomeSync,
  type HomeValue,
} from './home-sync.svelte';
import { ACTIVE_BOARD_KEY, mergeBoards, pickActiveBoard } from './home-boards';
import { homeLayout } from './layout.svelte';
import { resetLayout } from './model';
import { META } from './meta';
import { flushSave } from './persist';
import type { Layout } from './types';

class FakePrefs {
  HYDRATED = 'hydrated';
  COMMITTED = 'committed';
  values: Record<string, unknown> = {};
  sets: HomeValue[] = [];
  theirsFirst: unknown[] = [];
  status(): string {
    return this.HYDRATED;
  }
  committedValue(name: string): unknown {
    return this.values[name];
  }
  async set(name: string, value: unknown): Promise<{ status: string }> {
    this.sets.push(JSON.parse(JSON.stringify(value)) as HomeValue);
    if (this.theirsFirst.length) {
      this.values[name] = this.theirsFirst.shift();
      return { status: 'stale_revision' };
    }
    this.values[name] = JSON.parse(JSON.stringify(value));
    return { status: 'committed' };
  }
  subscribe(): () => void {
    return () => {};
  }
}

let prefs: FakePrefs;

const grid = (collapsed: boolean): Layout => ({ ...resetLayout(META, 'home'), heroCollapsed: collapsed });
const value = (...ids: string[]): HomeValue => ({
  v: 2,
  boards: ids.map((id) => ({ id, name: id, layout: grid(false) })),
  analytics_seed: 2,
});
const settle = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(WRITE_DELAY * 6);
};

async function open(...ids: string[]): Promise<void> {
  prefs.values[FIELD] = value(...ids);
  startHomeSync({ target: null });
  await hydrateHome();
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
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('the single layout value reads as one board, home, untouched', () => {
  const layout = grid(true);
  const read = parseHome({ v: 1, layout, analytics_seed: 1 });
  expect(read?.boards).toEqual([{ id: 'home', name: 'home', layout }]);
  expect(parseHome({ v: 2, boards: [] })).toBeNull();
  expect(parseHome({ v: 2, boards: [{ id: 'bad id', name: 'x', layout }] })).toBeNull();
});

test('pure rules: the active pick falls back, a merge keeps their boards and ours', () => {
  const boards = [{ id: 'home' }, { id: 'b-1' }];
  expect(pickActiveBoard(boards, 'b-1')).toBe('b-1');
  expect(pickActiveBoard(boards, 'gone')).toBe('home');
  expect(pickActiveBoard([{ id: 'b-1' }], null)).toBe('b-1');
  const mine = (id: string, c: boolean) => ({ id, name: id, layout: grid(c) });
  const merged = mergeBoards([mine('home', true), mine('mine', false)], [mine('home', false), mine('theirs', false)], 'home');
  expect(merged.map((b) => b.id)).toEqual(['home', 'theirs', 'mine']);
  expect(merged[0]!.layout.heroCollapsed).toBe(true);
});

const two = (active?: string): HomeValue => ({
  v: 2,
  boards: [
    { id: 'home', name: 'home', layout: grid(false) },
    { id: 'b-2', name: 'two', layout: grid(true) },
  ],
  analytics_seed: 2,
  ...(active ? { active } : {}),
});

test('the main window shows the synced active dashboard and follows a new one', async () => {
  prefs.values[FIELD] = two('b-2');
  startHomeSync({ target: null });
  await hydrateHome();
  expect(homeBoards.active).toBe('b-2');
  expect(homeLayout.state.layout.heroCollapsed).toBe(true);
  const { applyHome } = await import('./home-sync.svelte');
  applyHome(two('home'));
  expect(homeBoards.active).toBe('home');
  expect(homeLayout.state.layout.heroCollapsed).toBe(false);
  await settle();
  expect(prefs.sets).toHaveLength(0);
});

test('an upgrade keeps this browser\'s board and records it as active on the first write', async () => {
  localStorage.setItem(ACTIVE_BOARD_KEY, 'b-2');
  prefs.values[FIELD] = two();
  startHomeSync({ target: null });
  await hydrateHome();
  expect(homeBoards.active).toBe('b-2');
  homeLayout.setHeroCollapsed(false);
  await settle();
  expect(prefs.sets.at(-1)!.active).toBe('b-2');
});

test('an edit lands on the active board only', async () => {
  prefs.values[FIELD] = two('b-2');
  startHomeSync({ target: null });
  await hydrateHome();
  homeLayout.setHeroCollapsed(false);
  await settle();
  const sent = prefs.sets.at(-1)!;
  expect(sent.boards.find((b) => b.id === 'b-2')!.layout.heroCollapsed).toBe(false);
  expect(sent.boards.find((b) => b.id === 'home')!.layout.heroCollapsed).toBe(false);
  expect(sent.boards.find((b) => b.id === 'home')!.layout).toEqual(grid(false));
});

test('409 keeps the board another browser added and the active one it chose', async () => {
  await open('home');
  prefs.theirsFirst = [{ ...value('home', 'theirs'), active: 'theirs' }];
  homeLayout.setHeroCollapsed(true);
  await settle();
  expect(prefs.sets).toHaveLength(2);
  expect(prefs.sets[1]!.boards.map((b) => b.id)).toEqual(['home', 'theirs']);
  expect(prefs.sets[1]!.active).toBe('theirs');
});

test('the wallboard pop-out shows the board it was opened for and never writes', async () => {
  prefs.values[FIELD] = two();
  const { authFetch } = await import('../api/auth.svelte');
  const fetch = authFetch as unknown as ReturnType<typeof vi.fn>;
  fetch.mockResolvedValue({ values: { [FIELD]: prefs.values[FIELD] } });
  startHomeSync({ target: null, popout: true, board: 'b-2' });
  await vi.advanceTimersByTimeAsync(10);
  expect(homeBoards.active).toBe('b-2');
  expect(homeLayout.state.layout.heroCollapsed).toBe(true);
  homeLayout.setHeroCollapsed(false);
  await settle();
  expect(prefs.sets).toHaveLength(0);
  expect(fetch.mock.calls.some((call) => (call[1] as RequestInit | undefined)?.method === 'PUT')).toBe(false);
});

test('a dashboard pop-out saves only its own board, through its route', async () => {
  prefs.values[FIELD] = two('home');
  const { authFetch } = await import('../api/auth.svelte');
  const fetch = authFetch as unknown as ReturnType<typeof vi.fn>;
  fetch.mockResolvedValue({ values: { [FIELD]: prefs.values[FIELD] } });
  startHomeSync({ target: null, popout: true, board: 'b-2', edit: true });
  await vi.advanceTimersByTimeAsync(10);
  expect(homeBoards.active).toBe('b-2');
  homeLayout.setHeroCollapsed(false);
  await settle();
  const put = fetch.mock.calls.find((call) => (call[1] as RequestInit | undefined)?.method === 'PUT')!;
  expect(put[0]).toBe('/dashboards/b-2/layout');
  expect(JSON.parse(String((put[1] as RequestInit).body)).layout.heroCollapsed).toBe(false);
  expect(prefs.sets).toHaveLength(0);
});

test('clicking a non-default dashboard views it with no preference write, an edit saves that board only, the dashboards row clears it', async () => {
  const showLaunchpad = vi.fn();
  (globalThis as { App?: unknown }).App = { showLaunchpad };
  const { authFetch } = await import('../api/auth.svelte');
  const fetch = authFetch as unknown as ReturnType<typeof vi.fn>;
  fetch.mockResolvedValue({ values: {} });
  const { openMenuDashboard } = await import('../../lib/drawer-tabs/menu-dashboards.svelte');
  const { RAIL_RUN } = await import('../shell/rail-items');
  prefs.values[FIELD] = two('home');
  startHomeSync({ target: null });
  await hydrateHome();
  expect(homeLayout.state.layout.heroCollapsed).toBe(false);

  openMenuDashboard('b-2');
  await vi.advanceTimersByTimeAsync(10);
  expect(showLaunchpad).toHaveBeenCalledTimes(1);
  expect(homeBoards.viewing).toBe('b-2');
  expect(homeBoards.active).toBe('home');
  expect(homeLayout.state.layout.heroCollapsed).toBe(true);

  homeLayout.setHeroCollapsed(false);
  await settle();
  const put = fetch.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === 'PUT');
  expect(put.map((call) => call[0])).toEqual(['/dashboards/b-2/layout']);
  expect(prefs.sets).toHaveLength(0);

  RAIL_RUN['dashboards']!();
  await vi.advanceTimersByTimeAsync(10);
  expect(homeBoards.viewing).toBeNull();
  expect(homeLayout.state.layout.heroCollapsed).toBe(false);
  expect(prefs.sets).toHaveLength(0);
  delete (globalThis as { App?: unknown }).App;
}, 60000);
