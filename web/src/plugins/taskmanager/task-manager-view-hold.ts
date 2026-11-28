import type { HuddleItem } from './huddle-model';
import { sectionOf, statusSectionOf } from './task-manager-status-sections';

export type HoldLists = ReadonlyMap<string, readonly HuddleItem[]>;

export interface ViewHoldSnapshot {
  signature: string;
  lists: HoldLists;
}

export function placementOf(item: HuddleItem): string {
  return [sectionOf(item), statusSectionOf(item), item.group ?? '', item.position].join('|');
}

export function takeSnapshot(signature: string, lists: Iterable<readonly [string, readonly HuddleItem[]]>): ViewHoldSnapshot {
  return { signature, lists: new Map(lists) };
}

export function applyHold(snapshot: ViewHoldSnapshot | null, signature: string, list: string, live: readonly HuddleItem[]): HuddleItem[] {
  const frozen = snapshot?.signature === signature ? snapshot.lists.get(list) : undefined;
  if (!frozen) return live as HuddleItem[];
  const now = new Map(live.map((item) => [item.id, item]));
  return frozen.map((was) => {
    const item = now.get(was.id);
    return item && placementOf(item) === placementOf(was) ? item : was;
  });
}
