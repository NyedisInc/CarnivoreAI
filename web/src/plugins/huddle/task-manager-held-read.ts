import type { HuddleItem } from './huddle-model';
import { applyMarkRead } from './task-manager-optimistic';

const held = new Map<number, number | undefined>();

export function holdRead(id: number, through: number | undefined): () => void {
  held.set(id, through);
  return () => { if (held.get(id) === through) held.delete(id); };
}

export function overlayHeldReads(items: HuddleItem[]): HuddleItem[] {
  if (held.size === 0) return items;
  for (const item of items) if (held.has(item.id)) applyMarkRead(item, held.get(item.id));
  return items;
}

export function resetHeldReads(): void {
  held.clear();
}
