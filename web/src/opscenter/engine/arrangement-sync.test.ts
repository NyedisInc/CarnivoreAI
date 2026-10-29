/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { hydrateArrangement, localArrangement, rekeySlots, resetArrangementSync, startArrangementSync, WRITE_DELAY } from './arrangement-sync.svelte';
import { TERMINAL_LAYOUTS_FIELD as FIELD, parseArrangement, sameEntry, upsertEntry, emptyArrangement, type Arrangement } from './arrangement-model';
import { terminalLayout } from './layout.svelte';
import { activeTabFor, resetTabCache, selectTab, setGroups, tabsFor, TABS_KEY_PREFIX } from './tab-groups.svelte';
import { flushSave, storageKey } from './persist';
import { MAX_SESSION_LAYOUTS, SESSION_INDEX_KEY } from './session-layouts';
import { instancesOf, PRIMARY_SLOT } from './model';
import * as pointer from './pointer';

const KEY = 'cloude_api:1';
const OTHER = 'cloude_web:2';
const B = 'terminal:ses_b';
const C = 'terminal:ses_c';

class FakePrefs {
  HYDRATED = 'hydrated';
  COMMITTED = 'committed';
  hydrated = true;
  values: Record<string, unknown> = {};
  sets: unknown[] = [];
  theirsFirst: unknown[] = [];
  listeners: Array<(name: string, value: unknown, record: { state: string }) => void> = [];
  status(): string {
    return this.hydrated ? this.HYDRATED : 'not_hydrated';
  }
  committedValue(name: string): unknown {
    return this.values[name];
  }
  async set(name: string, value: unknown): Promise<{ status: string }> {
    this.sets.push(JSON.parse(JSON.stringify(value)));
    if (this.theirsFirst.length) {
      this.values[name] = this.theirsFirst.shift();
      return { status: 'stale_revision' };
    }
    this.values[name] = JSON.parse(JSON.stringify(value));
    this.emit(name, value);
    return { status: 'committed' };
  }
  subscribe(listener: (name: string, value: unknown, record: { state: string }) => void): () => void {
    this.listeners.push(listener);
    return () => {};
  }
  remote(name: string, value: unknown): void {
    this.values[name] = value;
    this.emit(name, value);
  }
  emit(name: string, value: unknown): void {
    for (const listener of this.listeners) listener(name, value, { state: this.COMMITTED });
  }
}

let prefs: FakePrefs;

function layoutWith(id: string) {
  terminalLayout.add('terminal', id);
  const layout = terminalLayout.snapshot();
  terminalLayout.resetAll();
  return JSON.parse(JSON.stringify(layout));
}

function arrangement(sessions: Arrangement['sessions']): Arrangement {
  return { v: 1, sessions };
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(WRITE_DELAY * 6);
}

beforeEach(() => {
  vi.useFakeTimers();
  prefs = new FakePrefs();
  (globalThis as { Preferences?: unknown }).Preferences = prefs;
});

afterEach(() => {
  resetArrangementSync();
  terminalLayout.bindSession('');
  resetTabCache();
  flushSave();
  localStorage.clear();
  delete (globalThis as { Preferences?: unknown }).Preferences;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('upsertEntry is pure, puts the key last, and keeps the session cap', () => {
  const entry = { layout: null, groups: {} };
  let map = emptyArrangement();
  for (let n = 0; n < MAX_SESSION_LAYOUTS; n += 1) map = upsertEntry(map, `s${n}`, entry);
  const next = upsertEntry(map, 's0', { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT] } } });
  expect(Object.keys(map.sessions)[0]).toBe('s0');
  expect(Object.keys(next.sessions).at(-1)).toBe('s0');
  const grown = upsertEntry(map, 'new', entry);
  expect(Object.keys(grown.sessions)).toHaveLength(MAX_SESSION_LAYOUTS);
  expect(grown.sessions.s0).toBeUndefined();
  expect(parseArrangement(undefined)).toBeNull();
  expect(parseArrangement(null)).toBeNull();
  expect(parseArrangement({ nonsense: 1 })).toEqual(emptyArrangement());
  expect(sameEntry({ layout: null, groups: { a: { tabs: ['x'] } } }, { groups: { a: { tabs: ['x'] } }, layout: null })).toBe(true);
});

test('hydrate: a present value shows the bound session and stores every other one locally', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  const layout = layoutWith('ses_x');
  prefs.values[FIELD] = arrangement({
    [OTHER]: { layout, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C] } } },
    [KEY]: { layout, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } } },
  });
  startArrangementSync(null);
  await hydrateArrangement();
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, B]);
  expect(JSON.stringify(terminalLayout.state.layout)).toContain('terminal:ses_x');
  expect(localStorage.getItem(storageKey('terminal', OTHER))).toContain('terminal:ses_x');
  expect(JSON.parse(localStorage.getItem(TABS_KEY_PREFIX + OTHER) ?? '{}').groups[PRIMARY_SLOT].tabs).toEqual([PRIMARY_SLOT, C]);
  await settle();
  expect(prefs.sets).toHaveLength(0);
});

test('a user operation writes the session entry once; a tab click (per device) writes nothing', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({});
  startArrangementSync(null);
  await hydrateArrangement();
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  terminalLayout.add('terminal', 'ses_x');
  await settle();
  expect(prefs.sets).toHaveLength(1);
  const sent = prefs.sets[0] as Arrangement;
  expect(sent.sessions[KEY]!.groups[PRIMARY_SLOT]!.tabs).toEqual([PRIMARY_SLOT, B]);
  expect(JSON.stringify(sent.sessions[KEY]!.layout)).toContain('terminal:ses_x');
  expect(JSON.stringify(sent)).not.toContain('active');
  selectTab(terminalLayout, PRIMARY_SLOT, B);
  await settle();
  expect(prefs.sets).toHaveLength(1);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(B);
});

test('follow: another device\'s change applies, keeps this device\'s active tab, and is never echoed', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({ [KEY]: { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } } } });
  startArrangementSync(null);
  await hydrateArrangement();
  selectTab(terminalLayout, PRIMARY_SLOT, B);
  prefs.remote(FIELD, arrangement({ [KEY]: { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C, B] } } } }));
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, C, B]);
  expect(activeTabFor(terminalLayout, PRIMARY_SLOT)).toBe(B);
  await settle();
  expect(prefs.sets).toHaveLength(0);
});

test('follow: a change arriving mid-drag waits for the drag to end', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({});
  startArrangementSync(null);
  await hydrateArrangement();
  const live = vi.spyOn(pointer, 'gestureActive').mockReturnValue(true);
  prefs.remote(FIELD, arrangement({ [KEY]: { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C] } } } }));
  await vi.advanceTimersByTimeAsync(1000);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT]);
  live.mockReturnValue(false);
  await vi.advanceTimersByTimeAsync(400);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, C]);
});

test('409: adopts the server value, replays the pending op once, and announces', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({});
  startArrangementSync(null);
  await hydrateArrangement();
  const theirs = arrangement({ [OTHER]: { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C] } } } });
  prefs.theirsFirst.push(theirs);
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  await settle();
  expect(prefs.sets).toHaveLength(2);
  const replayed = prefs.values[FIELD] as Arrangement;
  expect(Object.keys(replayed.sessions)).toEqual([OTHER, KEY]);
  expect(replayed.sessions[KEY]!.groups[PRIMARY_SLOT]!.tabs).toEqual([PRIMARY_SLOT, B]);
  expect(JSON.parse(localStorage.getItem(TABS_KEY_PREFIX + OTHER) ?? '{}').groups[PRIMARY_SLOT].tabs).toEqual([PRIMARY_SLOT, C]);
  expect(terminalLayout.state.announcement).toMatch(/another device/);
});

test('409 twice: the second loss adopts theirs as it stands, no third write', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({});
  startArrangementSync(null);
  await hydrateArrangement();
  const final = arrangement({ [KEY]: { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C] } } } });
  prefs.theirsFirst.push(arrangement({}), final);
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  await settle();
  expect(prefs.sets).toHaveLength(2);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, C]);
});

test('migration: absent sends this browser\'s stored arrangement once and leaves the legacy keys', async () => {
  localStorage.setItem(TABS_KEY_PREFIX + OTHER, JSON.stringify({ groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C] } }, active: { [PRIMARY_SLOT]: C } }));
  localStorage.setItem(SESSION_INDEX_KEY, JSON.stringify([]));
  startArrangementSync(null);
  await hydrateArrangement();
  await hydrateArrangement();
  expect(prefs.sets).toHaveLength(1);
  const sent = prefs.sets[0] as Arrangement;
  expect(sent.sessions[OTHER]!.groups[PRIMARY_SLOT]!.tabs).toEqual([PRIMARY_SLOT, C]);
  expect(JSON.stringify(sent)).not.toContain('active');
  expect(localStorage.getItem(TABS_KEY_PREFIX + OTHER)).not.toBeNull();
});

test('migration: a 409 means another device migrated first, and theirs is adopted', async () => {
  localStorage.setItem(TABS_KEY_PREFIX + OTHER, JSON.stringify({ groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C] } }, active: {} }));
  prefs.theirsFirst.push(arrangement({ [OTHER]: { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } } } }));
  startArrangementSync(null);
  await hydrateArrangement();
  expect(prefs.sets).toHaveLength(1);
  expect(JSON.parse(localStorage.getItem(TABS_KEY_PREFIX + OTHER) ?? '{}').groups[PRIMARY_SLOT].tabs).toEqual([PRIMARY_SLOT, B]);
});

test('migration: nothing stored locally writes nothing, and absent stays absent', async () => {
  startArrangementSync(null);
  await hydrateArrangement();
  expect(localArrangement().sessions).toEqual({});
  expect(prefs.sets).toHaveLength(0);
  expect(prefs.values[FIELD]).toBeUndefined();
});

test('before the preference block is read, a change waits rather than writing', async () => {
  prefs.hydrated = false;
  terminalLayout.bindSession('cloude_api', 1);
  startArrangementSync(null);
  setGroups(terminalLayout, { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } });
  await settle();
  expect(prefs.sets).toHaveLength(0);
  prefs.hydrated = true;
  prefs.values[FIELD] = arrangement({});
  await hydrateArrangement();
  await settle();
  expect((prefs.sets.at(-1) as Arrangement).sessions[KEY]!.groups[PRIMARY_SLOT]!.tabs).toEqual([PRIMARY_SLOT, B]);
});

const liveRow = (id: string, row: number) => ({ session: { id }, session_row_id: row });
const ROWS = [liveRow('ses_a', 1), liveRow('ses_b', 2)];

test('re-key (#612): app-id slots move onto session rows here and on the server; the unmappable drop once, counted', async () => {
  const info = vi.spyOn(console, 'info').mockImplementation(() => {});
  terminalLayout.bindSession('cloude_api', 1);
  const mine = layoutWith('ses_a');
  const other = layoutWith('ses_gone');
  const zombie = layoutWith('ses_zombie');
  prefs.values[FIELD] = arrangement({
    [OTHER]: { layout: other, groups: {} },
    [KEY]: { layout: mine, groups: { 'terminal:ses_a': { tabs: ['terminal:ses_a', B] } } },
  });
  startArrangementSync(null);
  await hydrateArrangement();
  selectTab(terminalLayout, 'terminal:ses_a', B);

  await rekeySlots(ROWS);

  const sent = prefs.sets.at(-1) as Arrangement;
  expect(sent.sessions[KEY]!.groups).toEqual({ 'terminal:row:1': { tabs: ['terminal:row:1', 'terminal:row:2'] } });
  expect(instancesOf(sent.sessions[KEY]!.layout!)).toEqual([PRIMARY_SLOT, 'terminal:row:1']);
  expect(instancesOf(sent.sessions[OTHER]!.layout!)).toEqual([PRIMARY_SLOT]);
  expect(instancesOf(terminalLayout.state.layout)).toEqual([PRIMARY_SLOT, 'terminal:row:1']);
  expect(tabsFor(terminalLayout, 'terminal:row:1')).toEqual(['terminal:row:1', 'terminal:row:2']);
  expect(activeTabFor(terminalLayout, 'terminal:row:1')).toBe('terminal:row:2');
  expect(info).toHaveBeenCalledWith(expect.stringContaining('dropped'), expect.objectContaining({ synced: 1 }));

  const later = arrangement({ ...sent.sessions, [OTHER]: { layout: zombie, groups: {} } });
  prefs.remote(FIELD, later);
  const writes = prefs.sets.length;
  await rekeySlots(ROWS);
  expect(prefs.sets).toHaveLength(writes);
  expect(JSON.stringify(prefs.values[FIELD])).toContain('terminal:ses_zombie');
});

test('re-key (#612): an empty listing drops nothing, because a failed probe can read as one', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({ [OTHER]: { layout: layoutWith('ses_a'), groups: {} } });
  startArrangementSync(null);
  await hydrateArrangement();
  await rekeySlots([]);
  expect(prefs.sets).toHaveLength(0);
  await rekeySlots(ROWS);
  expect(instancesOf((prefs.sets.at(-1) as Arrangement).sessions[OTHER]!.layout!)).toEqual([PRIMARY_SLOT, 'terminal:row:1']);
});

test('re-key (#612) 409: adopts the server value and replays the rewrite on it once', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  const withA = layoutWith('ses_a');
  prefs.values[FIELD] = arrangement({ [OTHER]: { layout: withA, groups: {} } });
  startArrangementSync(null);
  await hydrateArrangement();
  prefs.theirsFirst.push(arrangement({
    [OTHER]: { layout: withA, groups: {} },
    [KEY]: { layout: null, groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, B] } } },
  }));

  await rekeySlots(ROWS);

  expect(prefs.sets).toHaveLength(2);
  const replayed = prefs.sets[1] as Arrangement;
  expect(replayed.sessions[KEY]!.groups[PRIMARY_SLOT]!.tabs).toEqual([PRIMARY_SLOT, 'terminal:row:2']);
  expect(instancesOf(replayed.sessions[OTHER]!.layout!)).toEqual([PRIMARY_SLOT, 'terminal:row:1']);
  expect(tabsFor(terminalLayout, PRIMARY_SLOT)).toEqual([PRIMARY_SLOT, 'terminal:row:2']);
  expect(terminalLayout.state.announcement).toMatch(/another device/);
});

test('a phone fold (title-bar tap) is saved to that session\'s terminal_layouts entry on the tap', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({});
  startArrangementSync(null);
  await hydrateArrangement();
  terminalLayout.toggleCollapsed(PRIMARY_SLOT);
  await settle();
  expect(prefs.sets).toHaveLength(1);
  const sent = prefs.sets[0] as Arrangement;
  expect(sent.sessions[KEY]!.layout?.collapsed).toContain(PRIMARY_SLOT);
});

test('u161-02: a write that throws is kept and sent again, not lost with the cleared queue', async () => {
  terminalLayout.bindSession('cloude_api', 1);
  prefs.values[FIELD] = arrangement({});
  startArrangementSync(null);
  await hydrateArrangement();
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  const real = prefs.set.bind(prefs);
  vi.spyOn(prefs, 'set').mockRejectedValueOnce(new Error('layer fault')).mockImplementation(real);
  terminalLayout.add('terminal', 'ses_x');
  await settle();
  await settle();
  const last = prefs.sets.at(-1) as Arrangement;
  expect(JSON.stringify(last.sessions[KEY]!.layout)).toContain('terminal:ses_x');
});

test('u161-03: a migration whose write throws is retried on the next hydrate', async () => {
  localStorage.setItem(TABS_KEY_PREFIX + OTHER, JSON.stringify({ groups: { [PRIMARY_SLOT]: { tabs: [PRIMARY_SLOT, C] } }, active: {} }));
  localStorage.setItem(SESSION_INDEX_KEY, JSON.stringify([]));
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  const real = prefs.set.bind(prefs);
  vi.spyOn(prefs, 'set').mockRejectedValueOnce(new Error('layer fault')).mockImplementation(real);
  startArrangementSync(null);
  await hydrateArrangement();
  await hydrateArrangement();
  expect(prefs.sets).toHaveLength(1);
});
