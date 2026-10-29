import { taskOf } from '../../../cplugs/huddle/task-manager-design/adapter';
import { entriesOf } from '../../../cplugs/huddle/task-manager-design/entries';
import type { Task } from '../../../cplugs/huddle/task-manager-design/model';
import { isUnreadTask, unreadMessageCount } from './mk2-unread';
import { chipCount } from './mk2-chips';
import { AGGREGATE, type TaskManagerGroup, type TaskManagerListBody } from '../../../cplugs/huddle/huddle-model';
import { t } from '../../../lib/i18n/index.svelte';

export function headCountOf(tasks: readonly Task[]): number {
  return tasks.filter(isUnreadTask).length;
}

export function headCountText(count: number): string {
  return count > 0 ? t('cplug.huddle.tm.n_unread', { n: count }) : '';
}

export function allEntriesOf(groups: readonly TaskManagerGroup[] | null): ReturnType<typeof entriesOf> | null {
  return groups === null ? null : entriesOf(groups);
}

export function listEntriesOf(body: TaskManagerListBody | null, list: string): ReturnType<typeof entriesOf> | null {
  if (body === null || body.list !== list || list === AGGREGATE) return null;
  const group: TaskManagerGroup = { list, name: null, project_id: null, revision: body.revision, items: body.items };
  return entriesOf([group]);
}

export function groupEntriesOf(groups: readonly TaskManagerGroup[] | null, list: string): ReturnType<typeof entriesOf> | null {
  const group = groups?.find((g) => g.list === list);
  return group ? entriesOf([group]) : null;
}

export function allTasksOf(groups: readonly TaskManagerGroup[] | null): Task[] | null {
  return allEntriesOf(groups)?.map((entry) => taskOf(entry)) ?? null;
}

export function listTasksOf(body: TaskManagerListBody | null, list: string): Task[] | null {
  return listEntriesOf(body, list)?.map((entry) => taskOf(entry)) ?? null;
}

export function groupTasksOf(groups: readonly TaskManagerGroup[] | null, list: string): Task[] | null {
  return groupEntriesOf(groups, list)?.map((entry) => taskOf(entry)) ?? null;
}

export interface HeadCounts {
  unread: number;
  needsYou: number;
}

export function headCountsOf(entries: ReturnType<typeof entriesOf>): HeadCounts {
  const items = entries.map((entry) => entry.item);
  return { unread: items.reduce((sum, item) => sum + unreadMessageCount(item), 0), needsYou: chipCount('needs_you', items) };
}

export function needsYouOfGroups(groups: readonly TaskManagerGroup[] | null, only: string | null): number | null {
  const entries = only === null ? allEntriesOf(groups) : groupEntriesOf(groups, only);
  return entries === null ? null : headCountsOf(entries).needsYou;
}

export function needsYouText(count: number): string {
  return count > 0 ? t('cplug.huddle.tm.n_needs_you', { n: count }) : '';
}
