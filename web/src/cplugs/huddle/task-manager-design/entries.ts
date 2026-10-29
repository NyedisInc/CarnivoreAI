/*  hidden  */
import { isAgentList, type TaskManagerGroup } from '../huddle-model';
import { listLabel } from '../task-manager-schedule-project';
import type { Entry } from './task-view';

export function entriesOf(groups: readonly TaskManagerGroup[] | null, only: string | null = null): Entry[] {
  const out: Entry[] = [];
  for (const group of groups ?? []) {
    if (isAgentList(group.list) || (only !== null && group.list !== only)) continue;
    const project = listLabel(group.list, group.name);
    for (const item of group.items) {
      if (item.deleted || item.placeholder) continue;
      out.push({ item, project, list: group.list });
    }
  }
  return out;
}
