
import type { HuddleItem } from './huddle-model';

export function boundaryOf(item: Pick<HuddleItem, 'thread'> | null | undefined): number | undefined {
  let newest: number | undefined;
  for (const m of item?.thread ?? []) {
    if (m.author !== 'joe' && m.id > 0 && (newest === undefined || m.id > newest)) newest = m.id;
  }
  return newest;
}
