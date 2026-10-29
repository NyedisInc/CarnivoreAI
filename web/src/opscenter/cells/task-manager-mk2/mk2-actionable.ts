import { entriesOf } from '../../../cplugs/huddle/task-manager-design/entries';
import { stateOfItem } from '../../../cplugs/huddle/task-manager-design/adapter';
import type { TaskState } from '../../../cplugs/huddle/task-manager-design/model';
import type { HuddleItem, TaskManagerGroup } from '../../../cplugs/huddle/huddle-model';
import { actionableIdOf } from './mk2-task-tabs';

const INACTIVE: ReadonlySet<TaskState> = new Set<TaskState>(['closed', 'later']);

export function isActionableItem(item: HuddleItem): boolean {
  const state = stateOfItem(item);
  if (INACTIVE.has(state)) return false;
  return item.needs_you === true || !!item.needs_action || state === 'review' || state === 'question' || actionableIdOf(item) !== null;
}

export function actionableOfGroups(groups: readonly TaskManagerGroup[] | null, only: string | null): number | null {
  if (groups === null) return null;
  return entriesOf(groups, only).filter((entry) => isActionableItem(entry.item)).length;
}
