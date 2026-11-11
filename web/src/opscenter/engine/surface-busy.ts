import { gestureActive } from './pointer';

const busy = new Set<() => boolean>();

export function registerBusy(fn: () => boolean): () => void {
  busy.add(fn);
  return () => busy.delete(fn);
}

export function surfaceBusy(): boolean {
  if (gestureActive()) return true;
  for (const fn of busy) if (fn()) return true;
  return false;
}
