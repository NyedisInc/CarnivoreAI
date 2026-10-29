import { entriesOf } from '../../../cplugs/huddle/task-manager-design/entries';
import { stateOfItem } from '../../../cplugs/huddle/task-manager-design/adapter';
import { newMessageIds } from '../../../cplugs/huddle/task-manager-design/task-view';
import { newCount, type Task, type TaskState } from '../../../cplugs/huddle/task-manager-design/model';
import { unread } from '../../../cplugs/huddle/task-manager-design/unread';
import type { HuddleItem, TaskManagerGroup } from '../../../cplugs/huddle/huddle-model';

const INACTIVE: ReadonlySet<TaskState> = new Set<TaskState>(['closed', 'later']);

export function countsAsUnread(state: TaskState, flagged: boolean): boolean {
  return flagged && !INACTIVE.has(state);
}


export function isUnreadItem(item: HuddleItem): boolean {
  if (item.status === 'scheduled' && newMessageIds(item).length === 0) return false;
  return countsAsUnread(stateOfItem(item), item.unread === true);
}

export function unreadMessageCount(item: HuddleItem): number {
  if (!isUnreadItem(item)) return 0;
  return Math.max(1, newMessageIds(item).length);
}

export function isUnreadTask(task: Task): boolean {
  if (task.scheduled && newCount(task) === 0) return false;
  return countsAsUnread(task.state, unread(task));
}

export function unreadOfGroups(groups: readonly TaskManagerGroup[] | null, only: string | null): number | null {
  if (groups === null) return null;
  return entriesOf(groups, only).filter((entry) => isUnreadItem(entry.item)).length;
}
