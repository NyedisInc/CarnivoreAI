import { approveNow } from './task-submit';
import { deleteItem, huddle, itemsOnScreen } from './huddle.svelte';
import { lockReason, tickLockOf } from './review-lock';
import { t } from '../sdk';
import { statusOf } from './huddle-status';
import type { HuddleItem } from './huddle-model';

export type ConfirmMode = 'tick' | 'delete' | 'checks';

export const tickConfirm = $state<{ open: boolean; item: HuddleItem | null; mode: ConfirmMode }>({ open: false, item: null, mode: 'tick' });

export function uncheckedCount(item: HuddleItem): number {
  return (item.review_checks ?? []).filter((c) => !c.checked).length;
}

export async function tickItem(item: HuddleItem, next: boolean): Promise<boolean> {
  const lock = next ? tickLockOf(item, itemsOnScreen()) : null;
  if (lock) {
    huddle.notice = lockReason(lock, t);
    return false;
  }
  const unchecked = uncheckedCount(item);
  if (next && (unchecked > 0 || statusOf(item) !== 'review')) {
    tickConfirm.item = item;
    tickConfirm.mode = unchecked > 0 ? 'checks' : 'tick';
    tickConfirm.open = true;
    return false;
  }
  return approveNow(item, next);
}

export function askDelete(item: HuddleItem): void {
  tickConfirm.item = item;
  tickConfirm.mode = 'delete';
  tickConfirm.open = true;
}

export function closeTickConfirm(): void {
  tickConfirm.open = false;
}

export async function confirmTick(): Promise<boolean> {
  const { item, mode } = tickConfirm;
  closeTickConfirm();
  if (!item) return false;
  return mode === 'delete' ? deleteItem(item) : approveNow(item, true);
}
