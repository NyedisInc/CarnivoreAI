import { drawerEnv } from '../../lib/drawer/env';
import { whenLegacyBootComplete } from '../../lib/legacy-boot';

export const LAYOUT_TABS_KEY = 'cloude.layout_tabs';
export const LAYOUT_TABS_PREF_FIELD = 'layout_tabs';

interface PrefsApi {
  HYDRATED?: unknown;
  status?(): unknown;
  get?(field: string, fallback?: unknown): unknown;
  set?(field: string, value: unknown): Promise<unknown>;
  subscribe?(fn: (name: string, value: unknown) => void): () => void;
}

interface BridgeApi {
  read?(field: string, fallback: () => unknown): unknown;
  write?(field: string, value: string[], local: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

interface LayoutTabsGlobals {
  PreferenceBridge?: BridgeApi;
  Preferences?: PrefsApi;
}

function globals(): LayoutTabsGlobals {
  return drawerEnv() as LayoutTabsGlobals;
}

function parseTabs(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) return null;
  const seen = new Set<string>();
  const out: string[] = [];
  for (const one of raw) {
    if (typeof one === 'string' && one && !seen.has(one)) {
      seen.add(one);
      out.push(one);
    }
  }
  return out;
}

export function withTab(tabs: readonly string[], uuid: string): string[] {
  return !uuid || tabs.includes(uuid) ? [...tabs] : [...tabs, uuid];
}

export function closeTab(
  tabs: readonly string[], uuid: string, active: string,
): { tabs: string[]; open: string | null } {
  const at = tabs.indexOf(uuid);
  if (at < 0 || tabs.length <= 1) return { tabs: [...tabs], open: null };
  const rest = tabs.filter((one) => one !== uuid);
  return { tabs: rest, open: uuid === active ? (rest[at] ?? rest[rest.length - 1] ?? null) : null };
}

export function addable<T extends { layout_uuid: string }>(all: readonly T[], tabs: readonly string[]): T[] {
  return all.filter((one) => !tabs.includes(one.layout_uuid));
}

export function visibleTabs(tabs: readonly string[], known: readonly string[] | null, active: string): string[] {
  return tabs.filter((uuid) => uuid === active || known === null || known.includes(uuid));
}

function loadLocal(): string[] {
  try {
    const raw: unknown = JSON.parse(globalThis.localStorage?.getItem(LAYOUT_TABS_KEY) ?? '[]');
    return parseTabs(raw) ?? [];
  } catch {
    return [];
  }
}

function writeLocal(next: readonly string[]): void {
  try {
    globalThis.localStorage?.setItem(LAYOUT_TABS_KEY, JSON.stringify(next));
  } catch {
  }
}

function readShared(): string[] | null {
  const g = globals();
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.read === 'function') {
    return parseTabs(bridge.read(LAYOUT_TABS_PREF_FIELD, () => null));
  }
  const prefs = g.Preferences;
  if (!prefs || typeof prefs.get !== 'function') return null;
  if (typeof prefs.status === 'function' && prefs.status() !== (prefs.HYDRATED ?? 'hydrated')) return null;
  return parseTabs(prefs.get(LAYOUT_TABS_PREF_FIELD, undefined));
}

function load(): string[] {
  return readShared() ?? loadLocal();
}

export const layoutTabs: { uuids: string[] } = $state({ uuids: load() });

function applyRemote(value: unknown): boolean {
  const parsed = parseTabs(value);
  if (parsed === null) return false;
  layoutTabs.uuids = parsed;
  writeLocal(parsed);
  return true;
}

export function syncLayoutTabsFromPreferences(): void {
  const shared = readShared();
  if (shared !== null) applyRemote(shared);
}

export function startLayoutTabsSync(
  target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
  syncLayoutTabsFromPreferences();
  const g = globals();
  let unsub: () => void = () => {};
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.follow === 'function') {
    unsub = bridge.follow(LAYOUT_TABS_PREF_FIELD, (value) => { applyRemote(value); });
  } else if (g.Preferences && typeof g.Preferences.subscribe === 'function') {
    unsub = g.Preferences.subscribe((name, value) => {
      if (name === LAYOUT_TABS_PREF_FIELD) applyRemote(value);
    });
  }
  let stopped = false;
  whenLegacyBootComplete(target, () => {
    if (!stopped) syncLayoutTabsFromPreferences();
  });
  return () => {
    stopped = true;
    unsub();
  };
}

export function setTabs(next: string[]): void {
  const cleaned = parseTabs(next) ?? [];
  layoutTabs.uuids = cleaned;
  const saveLocal = (): void => writeLocal(cleaned);
  const g = globals();
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.write === 'function') {
    bridge.write(LAYOUT_TABS_PREF_FIELD, cleaned, saveLocal).catch((err: unknown) => {
      console.warn('LayoutTabs: could not share layout_tabs:', err);
    });
    return;
  }
  saveLocal();
  const prefs = g.Preferences;
  if (prefs && typeof prefs.set === 'function'
      && (typeof prefs.status !== 'function' || prefs.status() === (prefs.HYDRATED ?? 'hydrated'))) {
    prefs.set(LAYOUT_TABS_PREF_FIELD, cleaned).catch((err: unknown) => {
      console.warn('LayoutTabs: could not share layout_tabs:', err);
    });
  }
}

export function noteOpen(uuid: string): void {
  if (uuid && !layoutTabs.uuids.includes(uuid)) setTabs(withTab(layoutTabs.uuids, uuid));
}
