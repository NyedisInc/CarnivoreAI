import { t } from '../../lib/i18n/index.svelte';
import { whenLegacyBootComplete } from '../../lib/legacy-boot';
import {
  TERMINAL_LAYOUTS_FIELD as FIELD,
  emptyArrangement,
  parseArrangement,
  sameEntry,
  upsertEntry,
  type Arrangement,
  type ArrangementEntry,
} from './arrangement-model';
import { onArrangementChange } from './arrangement-events';
import { terminalLayout } from './layout.svelte';
import { activeTabsFor, adoptGroups, groupsFor, replaceTabs, storedTabKeys } from './tab-groups.svelte';
import { rekeyArrangement, rekeyEntry, type SlotRow } from './slot-identity';
import { sessions } from '../api';
import { untrack } from 'svelte';
import { gestureActive } from './pointer';
import { clear, flushSave, load, save, validate } from './persist';
import { forgetSession, isBareTerminal, readIndex, touchSession } from './session-layouts';
import { META } from './meta';
import type { Layout } from './types';

export const WRITE_DELAY = 600;

const RETRY_DELAY = 300;

export interface PreferencesApi {
  HYDRATED: string;
  COMMITTED: string;
  status(): string;
  committedValue(name: string): unknown;
  set(name: string, value: unknown): Promise<{ status: string }>;
  subscribe(listener: (name: string, value: unknown, record: { state: string } | undefined) => void): () => void;
}

function prefs(): PreferencesApi | null {
  const found = (globalThis as { Preferences?: PreferencesApi }).Preferences;
  return found && typeof found.set === 'function' ? found : null;
}

export function preferencesApi(): PreferencesApi | null {
  return prefs();
}

let synced: Arrangement | null = null;
const pending = new Map<string, ArrangementEntry>();
let held: Arrangement | null = null;
let applying = false;
let inflight = false;
let writeTimer: ReturnType<typeof setTimeout> | undefined;
let heldTimer: ReturnType<typeof setTimeout> | undefined;
let started = false;
let stops: Array<() => void> = [];

function currentEntry(key: string): ArrangementEntry {
  const layout = $state.snapshot(terminalLayout.state.layout) as Layout;
  return { layout: isBareTerminal(layout) ? null : layout, groups: $state.snapshot(groupsFor(key)) };
}

function noteLocal(key: string): void {
  if (applying || !key || key !== terminalLayout.session) return;
  const entry = currentEntry(key);
  const base = pending.get(key) ?? synced?.sessions[key];
  if (sameEntry(entry, base) && !pending.has(key)) return;
  pending.set(key, entry);
  scheduleWrite();
}

export function queueEntry(key: string, entry: ArrangementEntry): void {
  pending.set(key, entry);
  scheduleWrite();
}

function scheduleWrite(delay = WRITE_DELAY): void {
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  writeTimer = setTimeout(() => {
    writeTimer = undefined;
    void flush();
  }, delay);
}

function applyEntry(key: string, entry: ArrangementEntry): void {
  if (key === terminalLayout.session) {
    terminalLayout.adopt(entry.layout);
  } else {
    const checked = entry.layout ? validate(entry.layout, META, 'terminal') : null;
    if (checked?.layout && !checked.refusal) {
      save(checked.layout, 'terminal', key);
      flushSave('terminal', key);
      touchSession(key);
    } else {
      clear('terminal', key);
      forgetSession(key);
    }
  }
  adoptGroups(key, entry.groups);
}

export function applyArrangement(next: Arrangement): void {
  if (gestureActive()) {
    held = next;
    if (heldTimer === undefined) {
      heldTimer = setTimeout(() => {
        heldTimer = undefined;
        const value = held;
        held = null;
        if (value) applyArrangement(value);
      }, RETRY_DELAY);
    }
    return;
  }
  held = null;
  const before = synced;
  synced = next;
  applying = true;
  try {
    for (const [key, entry] of Object.entries(next.sessions)) {
      if (pending.has(key) || sameEntry(entry, before?.sessions[key])) continue;
      applyEntry(key, entry);
    }
  } finally {
    applying = false;
  }
}

async function flush(): Promise<void> {
  const api = prefs();
  if (pending.size === 0 || !api) return;
  if (inflight || gestureActive() || api.status() !== api.HYDRATED || synced === null) {
    scheduleWrite(RETRY_DELAY * 4);
    return;
  }
  const ops = [...pending];
  pending.clear();
  const replay = (base: Arrangement): Arrangement => ops.reduce((map, [key, entry]) => upsertEntry(map, key, entry), base);
  const next = replay(synced);
  inflight = true;
  try {
    const result = await api.set(FIELD, next);
    if (result.status === 'stale_revision') {
      await resolveConflict(api, replay);
    } else if (result.status === 'committed' || result.status === 'unchanged') {
      synced = next;
    } else if (result.status === 'refused') {
      for (const [key, entry] of ops) if (!pending.has(key)) pending.set(key, entry);
      scheduleWrite(RETRY_DELAY * 4);
    }
  } finally {
    inflight = false;
  }
  if (pending.size > 0) scheduleWrite();
}

async function resolveConflict(api: PreferencesApi, replay: (base: Arrangement) => Arrangement): Promise<void> {
  const theirs = parseArrangement(api.committedValue(FIELD)) ?? emptyArrangement();
  const merged = replay(theirs);
  applyArrangement(merged);
  const again = await api.set(FIELD, merged);
  if (again.status === 'committed' || again.status === 'unchanged') {
    terminalLayout.announce(t('opscenter.tabs.sync_merged'));
    return;
  }
  if (again.status === 'stale_revision') {
    applyArrangement(parseArrangement(api.committedValue(FIELD)) ?? emptyArrangement());
    terminalLayout.announce(t('opscenter.tabs.sync_lost'));
    return;
  }
  synced = theirs;
}

export function localArrangement(): Arrangement {
  const keys = [...new Set([...readIndex(), ...storedTabKeys()])].reverse();
  let map = emptyArrangement();
  for (const key of keys) {
    const opened = load(META, 'terminal', '', key);
    const layout = opened.stored && !isBareTerminal(opened.layout) ? opened.layout : null;
    const groups = groupsFor(key);
    if (!layout && Object.keys(groups).length === 0) continue;
    map = upsertEntry(map, key, { layout, groups });
  }
  return map;
}

let droppedOnce = false;

function rekeyLocal(rows: readonly SlotRow[], drop: boolean): number {
  const bound = terminalLayout.session;
  const keys = new Set([...readIndex(), ...storedTabKeys(), ...Object.keys(synced?.sessions ?? {})]);
  if (bound) keys.add(bound);
  let dropped = 0;
  applying = true;
  try {
    for (const key of keys) {
      const live = key === bound;
      const opened = live ? null : load(META, 'terminal', '', key);
      const layout = live ? ($state.snapshot(terminalLayout.state.layout) as Layout) : opened?.stored ? opened.layout : null;
      const result = rekeyEntry({ layout, groups: groupsFor(key), active: activeTabsFor(key) }, rows, drop);
      if (!result.changed) continue;
      dropped += result.dropped;
      if (result.layout && result.layout !== layout) {
        if (live) terminalLayout.adopt(result.layout);
        else {
          save(result.layout, 'terminal', key);
          flushSave('terminal', key);
        }
      }
      replaceTabs(key, result.groups, result.active);
    }
  } finally {
    applying = false;
  }
  return dropped;
}

export async function rekeySlots(rows: readonly SlotRow[]): Promise<void> {
  const api = prefs();
  if (api && (api.status() !== api.HYDRATED || synced === null)) return;
  if (inflight || gestureActive()) return;
  const drop = !droppedOnce && rows.length > 0;
  const droppedHere = rekeyLocal(rows, drop);
  const rewrite = (base: Arrangement): Arrangement => rekeyArrangement(base, rows, drop).map;
  const first = api && synced ? rekeyArrangement(synced, rows, drop) : null;
  if (droppedHere > 0 || (first?.dropped ?? 0) > 0) {
    console.info('[terminal tabs] dropped slots that name no live session', {
      here: droppedHere,
      synced: first?.dropped ?? 0,
    });
  }
  if (!api || !first || first.map === synced) {
    if (drop) droppedOnce = true;
    return;
  }
  inflight = true;
  try {
    const result = await api.set(FIELD, first.map);
    const sent = result.status === 'committed' || result.status === 'unchanged';
    if (result.status === 'stale_revision') await resolveConflict(api, rewrite);
    else if (sent) applyArrangement(first.map);
    if (drop && (sent || result.status === 'stale_revision')) droppedOnce = true;
  } finally {
    inflight = false;
  }
  if (pending.size > 0) scheduleWrite();
}

function watchListing(): () => void {
  return $effect.root(() => {
    $effect(() => {
      const rows = sessions.data;
      if (sessions.status !== 'ok' || !rows) return;
      untrack(() => {
        rekeySlots(rows).catch((error: unknown) => console.warn('[terminal tabs] re-key failed', error));
      });
    });
  });
}

async function migrate(api: PreferencesApi): Promise<void> {
  const mine = localArrangement();
  if (Object.keys(mine.sessions).length === 0) {
    synced = emptyArrangement();
    return;
  }
  synced = emptyArrangement();
  inflight = true;
  try {
    const result = await api.set(FIELD, mine);
    if (result.status === 'committed' || result.status === 'unchanged') synced = mine;
    else if (result.status === 'stale_revision') {
      applyArrangement(parseArrangement(api.committedValue(FIELD)) ?? emptyArrangement());
    }
  } finally {
    inflight = false;
  }
  if (pending.size > 0) scheduleWrite();
}

export async function hydrateArrangement(): Promise<void> {
  const api = prefs();
  if (!api || api.status() !== api.HYDRATED || inflight) return;
  const value = parseArrangement(api.committedValue(FIELD));
  if (value === null) {
    if (synced === null) await migrate(api);
  } else {
    applyArrangement(value);
  }
  if (sessions.status === 'ok' && sessions.data) await rekeySlots(sessions.data);
}

export function startArrangementSync(target: Window | null = typeof window !== 'undefined' ? window : null): void {
  if (started) return;
  started = true;
  stops.push(onArrangementChange(noteLocal));
  stops.push(watchListing());
  const api = prefs();
  if (api) {
    stops.push(
      api.subscribe((name, value, record) => {
        if (name !== FIELD || record?.state !== api.COMMITTED || inflight) return;
        const next = parseArrangement(value);
        if (next) applyArrangement(next);
      }),
    );
  }
  whenLegacyBootComplete(target, () => void hydrateArrangement());
  if (target) {
    const onVisible = (): void => {
      if (target.document?.visibilityState === 'visible') void hydrateArrangement();
    };
    target.document?.addEventListener('visibilitychange', onVisible);
    stops.push(() => target.document?.removeEventListener('visibilitychange', onVisible));
  }
}

export function resetArrangementSync(): void {
  for (const stop of stops) stop();
  stops = [];
  started = false;
  synced = null;
  held = null;
  droppedOnce = false;
  pending.clear();
  applying = false;
  inflight = false;
  if (writeTimer !== undefined) clearTimeout(writeTimer);
  if (heldTimer !== undefined) clearTimeout(heldTimer);
  writeTimer = undefined;
  heldTimer = undefined;
}
