
import { readMigrating } from '../../../lib/browser-storage-migrate';
import { drawerEnv } from '../../../lib/drawer/env';
import { whenLegacyBootComplete } from '../../../lib/legacy-boot';
import { RETIRED_WIDGET_SUCCESSOR } from '../../engine/retired-widget-ids';

export const WIDGET_STATE_PREF_FIELD = 'widget_state';
const MAX_WIDGET_STATE_ENTRY_BYTES = 4096;

export type StateHome = 'device' | 'placement' | 'shared';

export interface LocalStateField<V> {
  readonly home: 'device' | 'placement';
  readonly default: V;
  readonly valid: (value: unknown) => value is V;
  readonly legacyKey?: string;
  readonly viewportOnly?: boolean;
}

export interface SharedStateField<V> {
  readonly home: 'shared';
  readonly default: V;
  readonly valid: (value: unknown) => value is V;
  readonly via: { readonly read: () => unknown; readonly write: (value: V) => void };
}

export type StateField<V = unknown> = LocalStateField<V> | SharedStateField<V>;

export type StateSpec = Readonly<Record<string, StateField<never> | StateField<unknown> | StateField<string> | StateField<boolean> | StateField<number>>>;

export type StateValue<F> = F extends StateField<infer V> ? V : never;

export type WidgetState<S extends StateSpec> = { -readonly [K in keyof S]: StateValue<S[K]> };

export const STATE_NAME = /^[a-z][a-z0-9-]*$/;

export type WidgetStateMap = Record<string, Record<string, unknown>>;

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
  write?(field: string, value: WidgetStateMap, local: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

interface WidgetStateGlobals {
  PreferenceBridge?: BridgeApi;
  Preferences?: PrefsApi;
}

function globals(): WidgetStateGlobals {
  return drawerEnv() as WidgetStateGlobals;
}

export function parseWidgetStateMap(raw: unknown): WidgetStateMap | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const out: WidgetStateMap = {};
  for (const [widgetId, bucket] of Object.entries(raw as Record<string, unknown>)) {
    if (!widgetId || !bucket || typeof bucket !== 'object' || Array.isArray(bucket)) continue;
    out[widgetId] = { ...(bucket as Record<string, unknown>) };
  }
  return out;
}

const remoteState = $state<{ map: WidgetStateMap; rev: number }>({ map: {}, rev: 0 });
let sharedCache: WidgetStateMap = {};

function readSharedMap(): WidgetStateMap | null {
  const g = globals();
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.read === 'function') {
    return parseWidgetStateMap(bridge.read(WIDGET_STATE_PREF_FIELD, () => null));
  }
  const prefs = g.Preferences;
  if (!prefs) return null;
  if (typeof prefs.status === 'function' && prefs.status() !== (prefs.HYDRATED ?? 'hydrated')) return null;
  const raw = typeof prefs.get === 'function'
    ? prefs.get(WIDGET_STATE_PREF_FIELD, undefined)
    : typeof prefs.committedValue === 'function'
      ? prefs.committedValue(WIDGET_STATE_PREF_FIELD)
      : undefined;
  return parseWidgetStateMap(raw);
}

function cacheRemoteEntries(map: WidgetStateMap): void {
  for (const [widgetId, bucket] of Object.entries(map)) {
    for (const [entryKey, value] of Object.entries(bucket)) {
      if (value === undefined) continue;
      writeStored(`carnivore.${widgetId}.${entryKey}`, value);
    }
  }
}

function applyRemoteWidgetState(raw: unknown): boolean {
  const parsed = parseWidgetStateMap(raw);
  if (parsed === null) return false;
  sharedCache = parsed;
  remoteState.map = parsed;
  remoteState.rev += 1;
  cacheRemoteEntries(parsed);
  return true;
}

export function syncWidgetStateFromPreferences(): void {
  const shared = readSharedMap();
  if (shared !== null) applyRemoteWidgetState(shared);
}

export function startWidgetStateSync(
  target: Window | null = typeof window !== 'undefined' ? window : null,
): () => void {
  syncWidgetStateFromPreferences();
  const g = globals();
  let unsub: () => void = () => {};
  const bridge = g.PreferenceBridge;
  if (bridge && typeof bridge.follow === 'function') {
    unsub = bridge.follow(WIDGET_STATE_PREF_FIELD, (value) => { applyRemoteWidgetState(value); });
  } else if (g.Preferences && typeof g.Preferences.subscribe === 'function') {
    unsub = g.Preferences.subscribe((name, value) => {
      if (name === WIDGET_STATE_PREF_FIELD) applyRemoteWidgetState(value);
    });
  }
  let stopped = false;
  whenLegacyBootComplete(target, () => {
    if (!stopped) syncWidgetStateFromPreferences();
  });
  return () => {
    stopped = true;
    unsub();
  };
}

export function resetWidgetStateSync(): void {
  sharedCache = {};
  remoteState.map = {};
  remoteState.rev = 0;
}

function writeSharedField(widget: string, entryKey: string, value: unknown, storageKey: string): void {
  const saveLocal = (): void => writeStored(storageKey, value);
  const g = globals();
  const bridge = g.PreferenceBridge;
  const prefs = g.Preferences;
  const canBridge = Boolean(bridge && typeof bridge.write === 'function');
  const canPrefs = Boolean(
    prefs && typeof prefs.set === 'function'
    && (typeof prefs.status !== 'function' || prefs.status() === (prefs.HYDRATED ?? 'hydrated')),
  );
  if (!canBridge && !canPrefs) {
    saveLocal();
    return;
  }
  const base = readSharedMap() ?? sharedCache;
  const bucket: Record<string, unknown> = { ...(base[widget] ?? {}), [entryKey]: value };
  try {
    if (new TextEncoder().encode(JSON.stringify(bucket)).length > MAX_WIDGET_STATE_ENTRY_BYTES) {
      saveLocal();
      console.warn('carnivore: widget_state entry exceeds 4096 bytes, keeping local only', widget, entryKey);
      return;
    }
  } catch {
    saveLocal();
    return;
  }
  const next: WidgetStateMap = { ...base, [widget]: bucket };
  sharedCache = next;
  if (canBridge) {
    bridge!.write!(WIDGET_STATE_PREF_FIELD, next, saveLocal).catch((err: unknown) => {
      console.warn('carnivore: widget_state sync failed', widget, entryKey, err);
    });
    return;
  }
  saveLocal();
  prefs!.set!(WIDGET_STATE_PREF_FIELD, next).catch((err: unknown) => {
    console.warn('carnivore: widget_state sync failed', widget, entryKey, err);
  });
}

export function rememberedNames(state: StateSpec): string[] {
  return Object.keys(state);
}

export function stateKey(widget: string, name: string, placement?: string): string {
  return placement ? `carnivore.${widget}.${placement}.${name}` : `carnivore.${widget}.${name}`;
}

function widgetEntryKey(name: string, placement?: string): string {
  return placement ? `${placement}.${name}` : name;
}

export function readStored(key: string, read: (key: string) => string | null = (k) => globalThis.localStorage?.getItem(k) ?? null): unknown[] {
  let raw: string | null;
  try {
    raw = read(key);
  } catch (err) {
    console.warn('carnivore: widget state unreadable', key, err);
    return [];
  }
  if (raw === null) return [];
  try {
    return [JSON.parse(raw) as unknown, raw];
  } catch {
    return [raw];
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    globalThis.localStorage?.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
  } catch (err) {
    console.warn('carnivore: widget state not kept', key, err);
  }
}

export function initialValue<V>(field: LocalStateField<V>, key: string | null): V {
  const candidates = [...(key ? readStored(key) : []), ...(field.legacyKey ? readStored(field.legacyKey, readMigrating) : [])];
  const hit = candidates.find((value) => field.valid(value));
  return hit === undefined ? field.default : (hit as V);
}

export function adoptRetiredState(widget: string, store: Storage | undefined = globalThis.localStorage): number {
  const retired = Object.entries(RETIRED_WIDGET_SUCCESSOR)
    .filter(([, successor]) => successor === widget)
    .map(([id]) => id)
    .sort((a, b) => Number(a.startsWith('core.huddle')) - Number(b.startsWith('core.huddle')));
  if (!store || retired.length === 0) return 0;
  let copied = 0;
  try {
    const keys = Array.from({ length: store.length }, (_, at) => store.key(at)).filter((key): key is string => key !== null);
    for (const id of retired) {
      const prefix = `carnivore.${id}.`;
      for (const key of keys.filter((one) => one.startsWith(prefix))) {
        const target = `carnivore.${widget}.${key.slice(prefix.length)}`;
        const value = store.getItem(key);
        if (value === null || store.getItem(target) !== null) continue;
        store.setItem(target, value);
        copied += 1;
      }
    }
  } catch (err) {
    console.warn('carnivore: retired widget state not carried over', widget, err);
  }
  return copied;
}

const adoptedWidgets = new Set<string>();

export function resetAdoptedWidgets(): void {
  adoptedWidgets.clear();
}

export function bindState<S extends StateSpec>(widget: string, state: S, placement: () => string): WidgetState<S> {
  if (!adoptedWidgets.has(widget)) {
    adoptedWidgets.add(widget);
    adoptRetiredState(widget);
  }
  const held: Record<string, unknown> = $state({});
  const localRev: Record<string, number> = $state({});
  const sharedNow = readSharedMap();
  const out = {} as WidgetState<S>;
  for (const [name, field] of Object.entries(state) as [string, StateField<unknown>][]) {
    if (field.home === 'shared') {
      Object.defineProperty(out, name, {
        enumerable: true,
        get: () => {
          const value = field.via.read();
          return field.valid(value) ? value : field.default;
        },
        set: (value: unknown) => {
          if (field.valid(value)) field.via.write(value);
        },
      });
      continue;
    }
    const keyOf = (): string | null => (field.home === 'device' ? stateKey(widget, name) : placement() ? stateKey(widget, name, placement()) : null);
    const entryOf = (): string | null => (field.home === 'device' ? widgetEntryKey(name) : placement() ? widgetEntryKey(name, placement()) : null);
    const initialEntry = entryOf();
    const fromShared = !field.viewportOnly && initialEntry
      ? (sharedNow?.[widget]?.[initialEntry] ?? remoteState.map[widget]?.[initialEntry])
      : undefined;
    held[name] = fromShared !== undefined && field.valid(fromShared) ? fromShared : initialValue(field, keyOf());
    localRev[name] = remoteState.rev;
    Object.defineProperty(out, name, {
      enumerable: true,
      get: () => {
        if (!field.viewportOnly && remoteState.rev > (localRev[name] ?? 0)) {
          const entry = entryOf();
          const remoteVal = entry ? remoteState.map[widget]?.[entry] : undefined;
          if (remoteVal !== undefined && field.valid(remoteVal)) return remoteVal;
        }
        return held[name];
      },
      set: (value: unknown) => {
        if (!field.valid(value)) return;
        held[name] = value;
        localRev[name] = remoteState.rev;
        const key = keyOf();
        if (!key) return;
        if (field.viewportOnly) {
          writeStored(key, value);
          return;
        }
        const entry = entryOf();
        if (entry) writeSharedField(widget, entry, value, key);
        else writeStored(key, value);
      },
    });
  }
  return out;
}
