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
  hydrateHome,
  resetHomeSync,
  startHomeSync,
} from './home-sync.svelte';
import { homeLayout } from './layout.svelte';
import { resetLayout } from './model';
import { META } from './meta';
import { flushSave } from './persist';
import type { Layout, RowModel } from './types';

class FakePrefs {
  HYDRATED = 'hydrated';
  COMMITTED = 'committed';
  values: Record<string, unknown> = {};
  sets: Array<{ layout: Layout; analytics_seed: number }> = [];
  status(): string {
    return this.HYDRATED;
  }
  committedValue(name: string): unknown {
    return this.values[name];
  }
  async set(name: string, value: unknown): Promise<{ status: string }> {
    const sent = JSON.parse(JSON.stringify(value)) as { boards: Array<{ id: string; layout: Layout }> };
    this.sets.push({ ...sent, layout: sent.boards.find((b) => b.id === 'home')!.layout } as never);
    this.values[name] = JSON.parse(JSON.stringify(value));
    return { status: 'committed' };
  }
  subscribe(): () => void {
    return () => {};
  }
}

let prefs: FakePrefs;

function legacyValue(): { v: 1; layout: Layout; analytics_seed: number } {
  const layout = resetLayout(META, 'home');
  const band: RowModel = { id: 'r1', kind: 'px', size: 139, slots: [{ id: 'hero' as never, fr: 1 }] };
  return { v: 1, layout: { ...layout, rows: [band, ...layout.rows] }, analytics_seed: 2 };
}

function placed(layout: Layout): string[] {
  return layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  prefs = new FakePrefs();
  (globalThis as { Preferences?: unknown }).Preferences = prefs;
  homeLayout.resetAll();
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

test('a server value with the hero is shown without it and written back cleaned, once', async () => {
  prefs.values[FIELD] = legacyValue();
  expect(placed(legacyValue().layout)).toContain('hero');
  startHomeSync({ target: null });
  await hydrateHome();
  expect(placed(homeLayout.state.layout)).not.toContain('hero');
  await vi.advanceTimersByTimeAsync(WRITE_DELAY * 6);
  expect(prefs.sets).toHaveLength(1);
  expect(placed(prefs.sets[0]!.layout)).not.toContain('hero');
  expect(prefs.sets[0]!.analytics_seed).toBe(2);
  await hydrateHome();
  await vi.advanceTimersByTimeAsync(WRITE_DELAY * 6);
  expect(prefs.sets).toHaveLength(1);
});

test('the pop-out follows a value with the hero, shows it without, and never writes', async () => {
  pullBlock.values = { [FIELD]: legacyValue() };
  startHomeSync({ popout: true, target: null });
  await vi.advanceTimersByTimeAsync(WRITE_DELAY * 6);
  expect(placed(homeLayout.state.layout)).not.toContain('hero');
  expect(prefs.sets).toHaveLength(0);
});
