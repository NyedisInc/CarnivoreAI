/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('../api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/auth.svelte')>()),
  authFetch: vi.fn(async () => ({ values: {} })),
}));

import { TERMINAL_LAYOUTS_FIELD, type Arrangement } from './arrangement-model';
import { hydrateArrangement, queueEntry, resetArrangementSync, startArrangementSync } from './arrangement-sync.svelte';
import { HOME_LAYOUT_FIELD, hydrateHome, resetHomeSync, startHomeSync, type HomeValue } from './home-sync.svelte';
import { warroomChanged } from './arrangement-events';
import { terminalLayout, warroomLayout } from './layout.svelte';
import { META } from './meta';
import { resetLayout } from './model';
import { flushSave } from './persist';
import { resetTabCache } from './tab-groups.svelte';
import type { Layout, LayoutPage } from './types';
import { hydrateWarroom, resetWarroomSync, startWarroomSync, WARROOM_LAYOUT_FIELD } from './warroom-sync.svelte';

/** Retired cell id to the Mark II cell that takes its slot. */
const SUCCESSOR: Record<string, string> = {
  'task-manager': 'task-manager-mk2',
  'task-list': 'task-manager-mk2',
  'task-manager-all': 'task-manager-mk2-all',
};

class FakePrefs {
  HYDRATED = 'hydrated';
  COMMITTED = 'committed';
  values: Record<string, unknown> = {};
  sets: Array<{ name: string; value: unknown }> = [];
  status(): string {
    return this.HYDRATED;
  }
  committedValue(name: string): unknown {
    return this.values[name];
  }
  async set(name: string, value: unknown): Promise<{ status: string }> {
    const copy = JSON.parse(JSON.stringify(value)) as unknown;
    this.sets.push({ name, value: copy });
    this.values[name] = copy;
    return { status: 'committed' };
  }
  subscribe(): () => void {
    return () => {};
  }
}

let prefs: FakePrefs;

function savedWith(page: LayoutPage, retired: string): Layout {
  const layout = JSON.parse(JSON.stringify(resetLayout(META, page))) as Layout;
  const slot = layout.rows[0]!.slots[0]!;
  layout.hidden = [...(layout.hidden ?? []).filter((id) => id !== retired && id !== SUCCESSOR[retired]), slot.id];
  slot.id = retired as never;
  return layout;
}

function firstSlot(layout: unknown): { id: string; fr: number } {
  return (layout as Layout).rows[0]!.slots[0]! as { id: string; fr: number };
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(5000);
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  prefs = new FakePrefs();
  (globalThis as { Preferences?: unknown }).Preferences = prefs;
});

afterEach(() => {
  resetHomeSync();
  resetWarroomSync();
  resetArrangementSync();
  terminalLayout.bindSession('');
  resetTabCache();
  flushSave();
  localStorage.clear();
  delete (globalThis as { Preferences?: unknown }).Preferences;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('dashboards', () => {
  for (const [retired, successor] of Object.entries(SUCCESSOR)) {
    test(`a dashboard not on screen holding ${retired} is written back once with ${successor} in the same slot and width`, async () => {
      const other = savedWith('home', retired);
      const value: HomeValue = { v: 2, boards: [{ id: 'home', name: 'home', layout: resetLayout(META, 'home') }, { id: 'b2', name: 'ops', layout: other }], analytics_seed: 0 };
      prefs.values[HOME_LAYOUT_FIELD] = value;
      startHomeSync({ target: null });
      await hydrateHome();
      await settle();
      expect(prefs.sets).toHaveLength(1);
      const sent = (prefs.sets[0]!.value as HomeValue).boards.find((board) => board.id === 'b2')!;
      expect(firstSlot(sent.layout)).toEqual({ id: successor, fr: firstSlot(other).fr });
      expect(JSON.stringify(sent.layout)).not.toContain(`"${retired}"`);
      await hydrateHome();
      await settle();
      expect(prefs.sets).toHaveLength(1);
    });
  }
});

describe('a pop-out never writes', () => {
  test('a pop-out reading a board that holds a retired cell shows the successor and sends nothing', async () => {
    const value: HomeValue = { v: 2, boards: [{ id: 'home', name: 'home', layout: savedWith('home', 'task-list') }], analytics_seed: 0 };
    prefs.values[HOME_LAYOUT_FIELD] = value;
    startHomeSync({ popout: true, target: null });
    await hydrateHome();
    await settle();
    expect(prefs.sets).toHaveLength(0);
  });
});

describe('the war room', () => {
  test('a saved war room holding the flat list is written back once with Mark II in the same slot and width', async () => {
    const saved = savedWith('warroom', 'task-list');
    prefs.values[WARROOM_LAYOUT_FIELD] = { v: 1, layout: saved };
    startWarroomSync(null);
    hydrateWarroom();
    await settle();
    expect(prefs.sets).toHaveLength(1);
    const sent = (prefs.sets[0]!.value as { layout: Layout }).layout;
    expect(firstSlot(sent)).toEqual({ id: 'task-manager-mk2', fr: firstSlot(saved).fr });
  });
});

describe('a 409 never puts a migrated copy over another window\'s edit', () => {
  const OTHER_TAB = 'terminal:ses_z';

  test('arrangement: the other window\'s edit to the same session survives and is not resent over', async () => {
    const mine: Arrangement = { v: 1, sessions: { 'cloude_api:1': { layout: savedWith('terminal', 'task-list'), groups: { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-list'] } } } } };
    const theirs: Arrangement = { v: 1, sessions: { 'cloude_api:1': { layout: savedWith('terminal', 'task-manager-mk2'), groups: { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-manager-mk2', OTHER_TAB] } } } } };
    prefs.values[TERMINAL_LAYOUTS_FIELD] = mine;
    let first = true;
    const set = prefs.set.bind(prefs);
    prefs.set = async (name: string, value: unknown) => {
      if (first) {
        first = false;
        prefs.sets.push({ name, value });
        prefs.values[name] = theirs;
        return { status: 'stale_revision' };
      }
      return set(name, value);
    };
    startArrangementSync(null);
    await hydrateArrangement();
    await settle();
    const stored = prefs.values[TERMINAL_LAYOUTS_FIELD] as Arrangement;
    expect(stored.sessions['cloude_api:1']!.groups['terminal:@primary']!.tabs).toContain(OTHER_TAB);
    expect(JSON.stringify(stored)).not.toContain('task-list');
    expect(prefs.sets).toHaveLength(1);
  });

  test('arrangement: the other window\'s value still holding a retired id is migrated before it is sent back', async () => {
    const mine: Arrangement = { v: 1, sessions: { 'cloude_api:1': { layout: savedWith('terminal', 'task-list'), groups: { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-list'] } } } } };
    const theirs: Arrangement = { v: 1, sessions: {
      'cloude_api:1': { layout: savedWith('terminal', 'task-list'), groups: { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-list', OTHER_TAB] } } },
      'cloude_api:9': { layout: null, groups: { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-list'] } } },
    } };
    prefs.values[TERMINAL_LAYOUTS_FIELD] = mine;
    let first = true;
    const set = prefs.set.bind(prefs);
    prefs.set = async (name: string, value: unknown) => {
      if (first) {
        first = false;
        prefs.sets.push({ name, value });
        prefs.values[name] = theirs;
        return { status: 'stale_revision' };
      }
      return set(name, value);
    };
    startArrangementSync(null);
    await hydrateArrangement();
    queueEntry('cloude_api:3', { layout: null, groups: { 'terminal:@primary': { tabs: ['terminal:@primary'] } } });
    await settle();
    const stored = prefs.values[TERMINAL_LAYOUTS_FIELD] as Arrangement;
    expect(JSON.stringify(stored)).not.toContain('task-list');
    expect(stored.sessions['cloude_api:1']!.groups['terminal:@primary']!.tabs).toContain(OTHER_TAB);
    // exactly one more write
    expect(prefs.sets).toHaveLength(2);
    expect(JSON.stringify(prefs.sets[1]!.value)).not.toContain('task-list');
  });

  test('arrangement: a queued entry that still names a retired cell is sent swapped', async () => {
    startArrangementSync(null);
    await hydrateArrangement();
    queueEntry('cloude_api:2', { layout: savedWith('terminal', 'task-list'), groups: { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-list'] } } });
    await settle();
    expect(prefs.sets.length).toBeGreaterThan(0);
    expect(JSON.stringify(prefs.sets.at(-1)!.value)).not.toContain('task-list');
  });

  test('war room: the other window\'s value is adopted and, already migrated, nothing more is sent', async () => {
    prefs.values[WARROOM_LAYOUT_FIELD] = { v: 1, layout: savedWith('warroom', 'task-list') };
    const theirs = { v: 1, layout: { ...savedWith('warroom', 'task-manager-mk2'), collapsed: ['their-edit'] } };
    let first = true;
    const set = prefs.set.bind(prefs);
    prefs.set = async (name: string, value: unknown) => {
      if (first) {
        first = false;
        prefs.sets.push({ name, value });
        prefs.values[name] = theirs;
        return { status: 'stale_revision' };
      }
      return set(name, value);
    };
    startWarroomSync(null);
    hydrateWarroom();
    await settle();
    expect(prefs.sets).toHaveLength(1);
    expect(prefs.values[WARROOM_LAYOUT_FIELD]).toEqual(theirs);
  });
});

describe('terminal arrangements', () => {
  test('a session not on screen keeps its slot and its tab, now Mark II, and the map is written back once', async () => {
    const saved = savedWith('terminal', 'task-manager-all');
    const map: Arrangement = {
      v: 1,
      sessions: {
        'cloude_api:1': { layout: saved, groups: { 'terminal:@primary': { tabs: ['terminal:@primary', 'widget:core.task-list', 'widget:core.task-manager-mk2'] } } },
      },
    };
    prefs.values[TERMINAL_LAYOUTS_FIELD] = map;
    startArrangementSync(null);
    await hydrateArrangement();
    await settle();
    expect(prefs.sets).toHaveLength(1);
    const entry = (prefs.sets[0]!.value as Arrangement).sessions['cloude_api:1']!;
    expect(firstSlot(entry.layout)).toEqual({ id: 'task-manager-mk2-all', fr: firstSlot(saved).fr });
    expect(entry.groups['terminal:@primary']!.tabs).toEqual(['terminal:@primary', 'widget:core.task-manager-mk2']);
    await hydrateArrangement();
    await settle();
    expect(prefs.sets).toHaveLength(1);
  });
});

describe('war room: a user edit during an in-flight migration write', () => {
  for (const answer of ['stale_revision', 'refused', 'throw']) {
    test(`user edit survives a migration write that answers ${answer}`, async () => {
      const saved = savedWith('warroom', 'task-list');
      prefs.values[WARROOM_LAYOUT_FIELD] = { v: 1, layout: saved };
      const victim = 'task-manager-mk2';
      const theirs = { v: 1, layout: { ...savedWith('warroom', 'task-list'), collapsed: ['task-list'] } };
      let first = true;
      const set = prefs.set.bind(prefs);
      prefs.set = async (name: string, value: unknown) => {
        if (first) {
          first = false;
          prefs.sets.push({ name, value });
          warroomLayout.hide(victim as never);
          warroomChanged();
          if (answer === 'throw') throw new Error('net');
          if (answer === 'stale_revision') prefs.values[name] = theirs;
          return { status: answer };
        }
        return set(name, value);
      };
      startWarroomSync(null);
      hydrateWarroom();
      await settle();
      await settle();
      const stored = (prefs.values[WARROOM_LAYOUT_FIELD] as { layout: Layout }).layout;
      expect((stored.hidden ?? []).includes(victim as never)).toBe(true);
    });
  }
  test('a migration-only write that throws, then meets a 409, keeps the other window value', async () => {
    const saved = savedWith('warroom', 'task-list');
    prefs.values[WARROOM_LAYOUT_FIELD] = { v: 1, layout: saved };
    const theirs = { v: 1, layout: { ...savedWith('warroom', 'task-manager-mk2'), collapsed: ['task-manager-mk2'] } };
    let calls = 0;
    const set = prefs.set.bind(prefs);
    prefs.set = async (name: string, value: unknown) => {
      calls += 1;
      prefs.sets.push({ name, value });
      if (calls === 1) throw new Error('net');
      if (calls === 2) { prefs.values[name] = theirs; return { status: 'stale_revision' }; }
      return set(name, value);
    };
    startWarroomSync(null);
    hydrateWarroom();
    await settle();
    await settle();
    expect(prefs.values[WARROOM_LAYOUT_FIELD]).toEqual(theirs);
  });
});
