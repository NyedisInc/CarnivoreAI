import { drawerEnv } from '../../../lib/drawer/env';
import { whenLegacyBootComplete } from '../../../lib/legacy-boot';
import { ALL_FILTERS_ON, FILTER_KEYS } from './model';
import type { FilterKey, Filters } from './types';

export const TIMELINE_FILTERS_STORAGE_KEY = 'oc.timeline.filters';
export const TIMELINE_FILTERS_PREF_FIELD = 'timeline_filters';

interface PrefsApi {
  HYDRATED?: unknown;
  status?(): unknown;
  get?(field: string, fallback?: unknown): unknown;
  committedValue?(field: string): unknown;
  set?(field: string, value: unknown): Promise<unknown>;
  subscribe?(fn: (name: string, value: unknown) => void): () => void;
}

interface BridgeApi {
  read?(field: string, fallback: () => unknown): unknown;
  write?(field: string, value: Filters, local: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

interface TimelineFilterGlobals {
  PreferenceBridge?: BridgeApi;
  Preferences?: PrefsApi;
}

function globals(): TimelineFilterGlobals {
  return drawerEnv() as TimelineFilterGlobals;
}

export function parseTimelineFilters(raw: unknown): Filters | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  const out: Filters = { ...ALL_FILTERS_ON };
  let anyValid = false;
  for (const key of FILTER_KEYS) {
    if (typeof obj[key] === 'boolean') {
      out[key] = obj[key];
      anyValid = true;
    }
  }
  return anyValid ? out : null;
}

function loadLocal(): Filters {
  try {
    const raw: unknown = JSON.parse(globalThis.localStorage?.getItem(TIMELINE_FILTERS_STORAGE_KEY) ?? 'null');
    return parseTimelineFilters(raw) ?? { ...ALL_FILTERS_ON };
  } catch {
    return { ...ALL_FILTERS_ON };
  }
}

function writeLocal(next: Filters): void {
  try {
    globalThis.localStorage?.setItem(TIMELINE_FILTERS_STORAGE_KEY, JSON.stringify(next));
  } catch {
  }
}

function readShared(): Filters | null {
  const g = globals();
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.read === 'function') {
    return parseTimelineFilters(bridge.read(TIMELINE_FILTERS_PREF_FIELD, () => null));
  }
  const prefs = g.Preferences;
  if (!prefs) return null;
  if (typeof prefs.status === 'function' && prefs.status() !== (prefs.HYDRATED ?? 'hydrated')) return null;
  const raw = typeof prefs.get === 'function'
    ? prefs.get(TIMELINE_FILTERS_PREF_FIELD, undefined)
    : typeof prefs.committedValue === 'function'
      ? prefs.committedValue(TIMELINE_FILTERS_PREF_FIELD)
      : undefined;
  return parseTimelineFilters(raw);
}

function load(): Filters {
  return readShared() ?? loadLocal();
}

function persist(next: Filters): void {
  const snapshot: Filters = { ...next };
  const saveLocal = (): void => writeLocal(snapshot);
  const g = globals();
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.write === 'function') {
    bridge.write(TIMELINE_FILTERS_PREF_FIELD, snapshot, saveLocal).catch((err: unknown) => {
      console.warn('TimelineFilters: could not share timeline_filters:', err);
    });
    return;
  }
  saveLocal();
  const prefs = g.Preferences;
  if (prefs && typeof prefs.set === 'function'
      && (typeof prefs.status !== 'function' || prefs.status() === (prefs.HYDRATED ?? 'hydrated'))) {
    prefs.set(TIMELINE_FILTERS_PREF_FIELD, snapshot).catch((err: unknown) => {
      console.warn('TimelineFilters: could not share timeline_filters:', err);
    });
  }
}

class TimelineFilters {
  value = $state<Filters>(load());

  applyRemote(raw: unknown): boolean {
    const parsed = parseTimelineFilters(raw);
    if (parsed === null) return false;
    this.value = parsed;
    writeLocal(parsed);
    return true;
  }

  toggle(key: FilterKey): void {
    const next: Filters = { ...this.value, [key]: !this.value[key] };
    this.value = next;
    persist(next);
  }

  reset(): void {
    this.value = { ...ALL_FILTERS_ON };
  }
}

export const timelineFilters = new TimelineFilters();

export function syncTimelineFiltersFromPreferences(): void {
  const shared = readShared();
  if (shared !== null) timelineFilters.applyRemote(shared);
}

export function startTimelineFiltersSync(
  target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
  syncTimelineFiltersFromPreferences();
  const g = globals();
  let unsub: () => void = () => {};
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.follow === 'function') {
    unsub = bridge.follow(TIMELINE_FILTERS_PREF_FIELD, (value) => { timelineFilters.applyRemote(value); });
  } else if (g.Preferences && typeof g.Preferences.subscribe === 'function') {
    unsub = g.Preferences.subscribe((name, value) => {
      if (name === TIMELINE_FILTERS_PREF_FIELD) timelineFilters.applyRemote(value);
    });
  }
  let stopped = false;
  whenLegacyBootComplete(target, () => {
    if (!stopped) syncTimelineFiltersFromPreferences();
  });
  return () => {
    stopped = true;
    unsub();
  };
}
