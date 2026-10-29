
import { readMigrating } from '../../../lib/browser-storage-migrate';

export type StateHome = 'device' | 'placement' | 'shared';

export interface LocalStateField<V> {
  readonly home: 'device' | 'placement';
  readonly default: V;
  readonly valid: (value: unknown) => value is V;
  readonly legacyKey?: string;
}

/* already exists */
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

export function rememberedNames(state: StateSpec): string[] {
  return Object.keys(state);
}

export function stateKey(widget: string, name: string, placement?: string): string {
  return placement ? `carnivore.${widget}.${placement}.${name}` : `carnivore.${widget}.${name}`;
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

export function bindState<S extends StateSpec>(widget: string, state: S, placement: () => string): WidgetState<S> {
  const held: Record<string, unknown> = $state({});
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
    held[name] = initialValue(field, keyOf());
    Object.defineProperty(out, name, {
      enumerable: true,
      get: () => held[name],
      set: (value: unknown) => {
        if (!field.valid(value)) return;
        held[name] = value;
        const key = keyOf();
        if (key) writeStored(key, value);
      },
    });
  }
  return out;
}
