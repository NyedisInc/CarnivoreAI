import type { TaskManagerActor, HuddleItem } from './huddle-model';

export function shownAuthor(item: Pick<HuddleItem, 'created_by' | 'from_inbox'>): TaskManagerActor {
  return item.from_inbox?.direct ? 'joe' : item.created_by;
}
