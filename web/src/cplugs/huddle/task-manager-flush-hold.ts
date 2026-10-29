import type { TaskManagerListRow } from './huddle-model';

export const HOLD_MS = 15_000;

const holds = new Map<string, number>();

export function holdFlushed(keys: readonly string[], now: number = Date.now()): void {
  for (const key of keys) holds.set(key, now + HOLD_MS);
}

export function applyFlushHold(lists: TaskManagerListRow[], now: number = Date.now()): TaskManagerListRow[] {
  if (holds.size === 0) return lists;
  return lists.map((row) => {
    const until = holds.get(row.key);
    if (until === undefined) return row;
    if (now >= until || (row.waiting_to_send ?? 0) === 0) {
      holds.delete(row.key);
      return row;
    }
    return { ...row, waiting_to_send: 0, untold: false };
  });
}

export function resetFlushHold(): void {
  holds.clear();
}
