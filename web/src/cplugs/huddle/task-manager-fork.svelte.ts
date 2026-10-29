import { authFetch } from '../sdk';
import { findItem, huddle, write } from './huddle.svelte';
import { forkBody, type ForkDraft } from './task-manager-fork';
import type { HuddleItem } from './huddle-model';

export const forkDialog = $state<{ open: boolean; item: HuddleItem | null }>({ open: false, item: null });

export function openFork(item: HuddleItem): void {
  forkDialog.item = item;
  forkDialog.open = true;
}

export function closeFork(): void {
  forkDialog.open = false;
}

export async function submitFork(draft: ForkDraft): Promise<boolean> {
  const item = forkDialog.item;
  if (!item) return false;
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}/fork`, { method: 'POST', body: JSON.stringify(forkBody(item, draft)) }));
}

export function jumpToParent(parentId: number): boolean {
  if (!findItem(parentId)) return false;
  huddle.openId = parentId;
  requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-huddle-item="${parentId}"]`)?.scrollIntoView?.({ block: 'nearest' }));
  return true;
}
