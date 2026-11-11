/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

vi.mock('../api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/auth.svelte')>()),
  authFetch: vi.fn(async () => ({ values: {} })),
}));

import { applyHome, hydrateHome, resetHomeSync, startHomeSync, type HomeValue } from '../engine/home-sync.svelte';
import { homeLayout } from '../engine/layout.svelte';
import { META } from '../engine/meta';
import { resetLayout } from '../engine/model';
import { flushSave } from '../engine/persist';
import type { Layout } from '../engine/types';
import { blobForSend, commitDashLayout, dashGridFor, dashItems, loadDashGrid, SETTLE_MS } from './dash-store.svelte';
import { blobWithGrid, membershipOf } from './grid-data';
import { rowsSig } from './format/rows-sig';

class FakePrefs {
  HYDRATED = 'hydrated';
  COMMITTED = 'committed';
  values: Record<string, unknown> = {};
  sets: HomeValue[] = [];
  conflicts: unknown[] = [];
  status(): string {
    return this.HYDRATED;
  }
  committedValue(name: string): unknown {
    return this.values[name];
  }
  async set(name: string, value: unknown): Promise<{ status: string }> {
    this.sets.push(JSON.parse(JSON.stringify(value)) as HomeValue);
    if (this.conflicts.length) {
      this.values[name] = this.conflicts.shift();
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
const sentGrid = (at = -1): { rows: Layout['rows']; grid: { rowsSig: string; layouts: { '24': { id: string; x: number; y: number }[] } } } =>
  (prefs.sets.at(at)!.boards[0]!.layout as never);

beforeEach(async () => {
  vi.useFakeTimers();
  localStorage.clear();
  prefs = new FakePrefs();
  (globalThis as { Preferences?: unknown }).Preferences = prefs;
  homeLayout.resetAll();
  prefs.values['home_layout'] = { v: 2, boards: [{ id: 'home', name: 'home', layout: JSON.parse(JSON.stringify(resetLayout(META, 'home'))) }], analytics_seed: 2 };
  startHomeSync({ target: null });
  await hydrateHome();
  prefs.sets = [];
});

afterEach(() => {
  resetHomeSync();
  flushSave();
  localStorage.clear();
  delete (globalThis as { Preferences?: unknown }).Preferences;
  vi.useRealTimers();
});

test('a settled gesture is one save, trailing SETTLE_MS, carrying grid beside byte-identical rows', async () => {
  const rows = JSON.stringify(homeLayout.state.layout.rows);
  const items = dashItems(homeLayout.state.layout, 24).map((i, k) => (k === 0 ? { ...i, w: i.w + 1 } : i));
  commitDashLayout(homeLayout.state.layout, 24, items);
  await vi.advanceTimersByTimeAsync(SETTLE_MS - 10);
  expect(prefs.sets).toHaveLength(0);
  await vi.advanceTimersByTimeAsync(20);
  expect(prefs.sets).toHaveLength(1);
  const sent = sentGrid();
  expect(JSON.stringify(sent.rows)).toBe(rows);
  expect(sent.grid.rowsSig).toBe(rowsSig(sent.rows));
  expect(sent.grid.layouts['24'].map((i) => i.id).sort()).toEqual(membershipOf(sent.rows).sort());
});

test('a remote value carrying a grid is shown with that arrangement', () => {
  const layout = JSON.parse(JSON.stringify(blobForSend(homeLayout.state.layout as Layout))) as { grid: { layouts: { '24': { id: string; x: number; y: number; w: number; h: number }[] } } };
  const first = layout.grid.layouts['24'][0]!;
  layout.grid.layouts['24'] = layout.grid.layouts['24'].map((i) => (i === first ? { ...i, y: 40 } : i));
  loadDashGrid('home', layout);
  expect(dashItems(homeLayout.state.layout, 24).find((i) => i.id === first.id)!.y).toBeGreaterThanOrEqual(0);
  applyHome({ v: 2, boards: [{ id: 'home', name: 'home', layout: layout as never }], analytics_seed: 2 });
  expect(dashItems(homeLayout.state.layout, 24)).toHaveLength(membershipOf(homeLayout.state.layout.rows).length);
});

test('a widget removed through the old path keeps every survivor in place and the next save drops it', async () => {
  const before = dashItems(homeLayout.state.layout, 24);
  const gone = before[0]!.id;
  homeLayout.hide(gone);
  const after = dashItems(homeLayout.state.layout, 24);
  expect(after.some((i) => i.id === gone)).toBe(false);
  await vi.advanceTimersByTimeAsync(2000);
  expect(sentGrid().grid.layouts['24'].some((i) => i.id === gone)).toBe(false);
  expect(sentGrid().rows.flatMap((r) => r.slots.map((s) => s.id))).not.toContain(gone);
});

test('409: the server value is adopted and this arrangement is replayed once', async () => {
  const theirs = { v: 2, boards: [{ id: 'home', name: 'home', layout: JSON.parse(JSON.stringify(resetLayout(META, 'home'))) }], analytics_seed: 2 };
  prefs.conflicts.push(theirs);
  commitDashLayout(homeLayout.state.layout, 24, dashItems(homeLayout.state.layout, 24).map((i, k) => (k === 0 ? { ...i, w: i.w + 1 } : i)));
  await vi.advanceTimersByTimeAsync(SETTLE_MS + 50);
  expect(prefs.sets).toHaveLength(2);
  expect(sentGrid(1).grid).toBeDefined();
});

const manyRows = (n: number): Layout => {
  const rows = Array.from({ length: n }, (_, k) => ({
    id: `r${k}`,
    kind: 'px' as const,
    size: 100,
    slots: [{ id: `analytics:00000000-0000-4000-8000-${String(k).padStart(12, '0')}` as never, fr: 1 }],
  }));
  return { v: 6, rows, hidden: [], heroCollapsed: false, collapsed: [] } as unknown as Layout;
};

const bytesOf = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).length;

test('a board past the grid item limit sends its rows alone', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  const over = manyRows(250);
  const out = blobForSend(over);
  expect('grid' in out).toBe(false);
  expect(out.rows).toBe(over.rows);
  warn.mockRestore();
});

test('a board whose rows fit the byte cap but whose grid does not sends its rows alone and warns with the sizes', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  const cap = 16384;
  let n = 1;
  let withGrid = 0;
  for (; n < 240; n++) {
    withGrid = bytesOf(blobWithGrid(manyRows(n), dashGridFor(manyRows(n))));
    if (withGrid > cap) break;
  }
  const board = manyRows(n);
  expect(bytesOf(board)).toBeLessThan(cap);
  expect(withGrid).toBeGreaterThan(cap);
  warn.mockClear();
  const out = blobForSend(board);
  expect('grid' in out).toBe(false);
  expect(out.rows).toBe(board.rows);
  expect(warn).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('pass the layout cap'), { bytes: withGrid, cap });
  warn.mockRestore();
});

test('control: a board under the cap keeps its grid', () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  const small = manyRows(5);
  expect('grid' in blobForSend(small)).toBe(true);
  expect(warn).not.toHaveBeenCalled();
  warn.mockRestore();
});
