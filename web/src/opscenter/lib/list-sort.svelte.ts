
import { readChoice, writeChoice } from '../../lib/ui/prefs.svelte';

export interface SortPref<K extends string> {
  readonly value: K;
  set(next: K): void;
}

export function createSortPref<K extends string>(
  storageKey: string,
  keys: readonly K[],
  fallback: K,
): SortPref<K> {
  let current = $state<K>(readChoice(storageKey, keys, fallback));
  return {
    get value(): K {
      return current;
    },
    set(next: K): void {
      current = next;
      writeChoice(storageKey, next);
    },
  };
}
