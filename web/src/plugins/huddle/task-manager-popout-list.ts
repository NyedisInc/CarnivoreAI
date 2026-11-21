import { listFromSearch } from './huddle-model';

export function popoutListKey(windowName: string): string {
  return `carnivore.huddle.popout.list:${windowName}`;
}

export function firstPopoutList(storage: Pick<Storage, 'getItem'> | null, windowName: string, search: string): string | null {
  let stored: string | null = null;
  try {
    stored = storage?.getItem(popoutListKey(windowName)) ?? null;
  } catch {
  }
  return (stored !== null ? listFromSearch(`?list=${encodeURIComponent(stored)}`) : null) ?? listFromSearch(search);
}

export function rememberPopoutList(storage: Pick<Storage, 'setItem'> | null, windowName: string, key: string): void {
  try {
    storage?.setItem(popoutListKey(windowName), key);
  } catch {
  }
}
