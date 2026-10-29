import { serverKey } from './huddle-model';
import { sendLists } from './huddle-send-many.svelte';
import { setApproved } from './huddle.svelte';
import type { HuddleItem } from './huddle-model';

/* did not answer */
export async function submitNow(list: string, save: () => Promise<boolean | 'kept'>, options: { immediate?: boolean } = {}): Promise<boolean> {
  const saved = await save();
  if (!saved) return false;
  if (saved === 'kept') return true;
  return sendLists([serverKey(list)], { queue: options.immediate !== true });
}

export function approveNow(item: HuddleItem, approved: boolean): Promise<boolean> {
  return submitNow(item.list, () => setApproved(item, approved));
}
