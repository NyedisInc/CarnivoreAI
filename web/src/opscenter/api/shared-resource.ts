import type { Resource } from './poll.svelte';

export interface SharedResources<K, T> {
  hold(key: K, make: () => Resource<T>): Resource<T>;
  drop(key: K): void;
}

export function sharedResources<K, T>(): SharedResources<K, T> {
  const cache = new Map<K, { resource: Resource<T>; refs: number }>();
  return {
    hold(key, make) {
      let entry = cache.get(key);
      if (!entry) {
        entry = { resource: make(), refs: 0 };
        cache.set(key, entry);
      }
      entry.refs += 1;
      return entry.resource;
    },
    drop(key) {
      const entry = cache.get(key);
      if (!entry) return;
      entry.refs -= 1;
      if (entry.refs <= 0) {
        entry.resource.stop();
        cache.delete(key);
      }
    },
  };
}
