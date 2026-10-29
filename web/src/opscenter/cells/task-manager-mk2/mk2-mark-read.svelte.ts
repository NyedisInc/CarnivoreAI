import { heldRead } from '../../../cplugs/huddle/huddle.svelte';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';

export const MARK_READ_HOLD_SECONDS = 5;

export const markReadHolds: Record<number, number> = $state({});

const sends = new Map<number, ReturnType<typeof setTimeout>>();

const reverts = new Map<number, () => void>();

export function holdLeft(id: number): number | null {
  const until = markReadHolds[id];
  return until === undefined ? null : Math.max(1, Math.ceil((until - Date.now()) / 1000));
}

export function undoMarkRead(id: number, restore = true): void {
  const send = sends.get(id);
  if (send !== undefined) clearTimeout(send);
  sends.delete(id);
  delete markReadHolds[id];
  const revert = reverts.get(id);
  reverts.delete(id);
  if (restore) revert?.();
}

export function pressMarkRead(item: HuddleItem): void {
  if (sends.has(item.id)) return undoMarkRead(item.id);
  const held = heldRead(item);
  if (!held) return;
  reverts.set(item.id, held.undo);
  markReadHolds[item.id] = Date.now() + MARK_READ_HOLD_SECONDS * 1000;
  sends.set(item.id, setTimeout(() => {
    undoMarkRead(item.id, false);
    void held.send();
  }, MARK_READ_HOLD_SECONDS * 1000));
}
