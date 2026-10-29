import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { statusOf } from '../../../cplugs/huddle/huddle-status';
import { titleOf } from '../../../cplugs/huddle/task-manager-design/task-view';

export interface Mk2SubtaskRow { id: number; title: string; statusKey: string; owner: string }

export function subtasksOf(parentId: number, items: readonly HuddleItem[]): Mk2SubtaskRow[] {
  return items.filter((i) => i.forked_from === parentId && !i.deleted).map((i) => ({
    id: i.id, title: titleOf(i), statusKey: `opscenter.cell.task_manager_mk2.sub_status.${statusOf(i)}`, owner: i.tagged_by || i.created_by,
  }));
}
