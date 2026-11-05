import type { Resource } from './poll.svelte';

export interface LeaseHooks<K, V> {
  make?: (key: K) => V;
  onLast?: (value: V, key: K) => void | Promise<void>;
  dispose?: (value: V, key: K) => void;
}

export interface KeyedLeases<K, V> {
  hold(key: K, make?: (key: K) => V): V;
  release(key: K): void | Promise<void>;
  values(): V[];
  clear(): void;
}

interface Entry<V> {
  value: V;
  holds: number;
}

function isThenable(value: unknown): value is PromiseLike<void> {
  return typeof value === 'object' && value !== null && typeof (value as { then?: unknown }).then === 'function';
}

export function keyedLeases<K, V>(hooks: LeaseHooks<K, V> = {}): KeyedLeases<K, V> {
  const live = new Map<K, Entry<V>>();

  function finish(key: K, entry: Entry<V>): void {
    if (entry.holds !== 0 || live.get(key) !== entry) return;
    live.delete(key);
    hooks.dispose?.(entry.value, key);
  }

  return {
    hold(key, make) {
      let entry = live.get(key);
      if (!entry) {
        const build = make ?? hooks.make;
        if (!build) throw new TypeError('keyed-leases/no-factory');
        entry = { value: build(key), holds: 0 };
        live.set(key, entry);
      }
      entry.holds += 1;
      return entry.value;
    },
    release(key) {
      const entry = live.get(key);
      if (!entry) return undefined;
      entry.holds -= 1;
      if (entry.holds > 0) return undefined;
      const pending = hooks.onLast?.(entry.value, key);
      if (isThenable(pending)) return Promise.resolve(pending).then(() => finish(key, entry));
      finish(key, entry);
      return undefined;
    },
    values: () => [...live.values()].map((entry) => entry.value),
    clear() {
      for (const [key, entry] of live) hooks.dispose?.(entry.value, key);
      live.clear();
    },
  };
}

export interface SharedResources<K, T> {
  hold(key: K, make: () => Resource<T>): Resource<T>;
  drop(key: K): void;
}

export function sharedResources<K, T>(): SharedResources<K, T> {
  const leases = keyedLeases<K, Resource<T>>({ dispose: (resource) => resource.stop() });
  return {
    hold: (key, make) => leases.hold(key, make),
    drop: (key) => void leases.release(key),
  };
}
