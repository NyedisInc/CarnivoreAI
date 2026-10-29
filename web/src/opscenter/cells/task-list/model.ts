import { visibleItems, type TaskManagerGroup, type HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { statusOf } from '../../../cplugs/huddle/huddle-status';
import { statusSections, sectionOf, type TaskManagerSectionKey } from '../../../cplugs/huddle/task-manager-status-sections';
import { postKindOf, unreadPosts, type TaskManagerPostKind } from '../../../cplugs/huddle/task-manager-posts';
import type { TaskManagerMessage } from '../../../cplugs/huddle/huddle-model';
import { latestMessage } from '../../../cplugs/huddle/huddle-density';
import { mdPlain } from '../../../cplugs/huddle/task-manager-markdown';
import type { BadgeStatus } from '../../../cplugs/huddle/task-manager-prefs.svelte';
import { listLabel } from '../../../cplugs/huddle/task-manager-schedule-project';
import type { PlacementOptions } from '../../widgets/placement-options';

export const LIST_ORDER: readonly BadgeStatus[] = Object.freeze(['question', 'review', 'working', 'waiting', 'scheduled', 'open'] as BadgeStatus[]);

export function statusOption(status: BadgeStatus): string {
  return `st_${status}`;
}

export const DENSITY_OPTION = 'density';

export type ListDensity = 'compact' | 'full';

export function statusTicked(options: PlacementOptions | undefined, status: BadgeStatus): boolean {
  return options?.[statusOption(status)] !== false;
}

export function densityOf(options: PlacementOptions | undefined): ListDensity {
  return options?.[DENSITY_OPTION] === 'full' ? 'full' : 'compact';
}

export const GROUP_OPTION = 'group';

export type ListGroupBy = 'status' | 'project';

export function groupOf(options: PlacementOptions | undefined): ListGroupBy {
  return options?.[GROUP_OPTION] === 'project' ? 'project' : 'status';
}

export type ListStatus = BadgeStatus | 'todo' | 'done';

export interface ListRow {
  key?: string;
  id: number;
  list: string;
  project: string;
  status: ListStatus;
  title: string;
  atMs: number | null;
  who: 'claude' | 'joe' | null;
  last: string;
  item: HuddleItem;
}

function live(item: HuddleItem): boolean {
  return !item.deleted && !item.placeholder;
}

export function rowOf(item: HuddleItem, project = item.list, any = false): ListRow | null {
  const status = statusOf(item);
  if (!any && !LIST_ORDER.includes(status as BadgeStatus)) return null;
  const last = latestMessage(item);
  const fire = status === 'scheduled' ? item.start_trigger?.fire_at : undefined;
  const at = fire ?? last?.created_at ?? null;
  return {
    id: item.id,
    list: item.list,
    project,
    status: status as ListStatus,
    title: mdPlain(item.title || item.text),
    atMs: at ? at * 1000 : null,
    who: last && status !== 'question' ? last.author : null,
    last: last ? mdPlain(last.text) : '',
    item,
  };
}

export function listRows(groups: readonly TaskManagerGroup[] | null, options?: PlacementOptions): ListRow[] {
  const rows: ListRow[] = [];
  for (const group of groups ?? []) {
    for (const item of group.items) {
      if (!live(item)) continue;
      const row = rowOf(item, listLabel(group.list, group.name));
      if (row && statusTicked(options, row.status as BadgeStatus)) rows.push(row);
    }
  }
  const rank = (row: ListRow): number => LIST_ORDER.indexOf(row.status as BadgeStatus);
  const when = (row: ListRow): number => row.atMs ?? 0;
  return rows.sort((a, b) => rank(a) - rank(b) || (a.status === 'scheduled' ? when(a) - when(b) : when(b) - when(a)) || a.id - b.id);
}

export interface ListSection {
  key: string;
  by: ListGroupBy;
  label: string;
  status: ListStatus | null;
  rows: ListRow[];
}

export function sectionsOf(rows: readonly ListRow[], by: ListGroupBy): ListSection[] {
  const out = new Map<string, ListSection>();
  for (const row of rows) {
    const key = by === 'status' ? row.status : row.list;
    const found = out.get(key) ?? { key, by, label: by === 'status' ? '' : row.project, status: by === 'status' ? row.status : null, rows: [] };
    found.rows.push(row);
    out.set(key, found);
  }
  return [...out.values()];
}

const MARK_POSTS: Readonly<Record<string, TaskManagerPostKind>> = { look: 'attention', info: 'info' };

export function isPostMark(kind: string): boolean {
  return kind in MARK_POSTS;
}

function rowOfPost(item: HuddleItem, post: TaskManagerMessage, project: string): ListRow {
  const base = rowOf(item, project, true)!;
  return { ...base, key: `${item.id}:${post.id}`, title: mdPlain(post.text), atMs: post.created_at * 1000, who: post.author, last: mdPlain(item.title || item.text) };
}

export function statusRows(groups: readonly TaskManagerGroup[] | null, list: string, kind: string, hide = false, marked = false): ListRow[] {
  const group = (groups ?? []).find((one) => one.list === list);
  if (!group) return [];
  const project = listLabel(group.list, group.name);
  const items = group.items.filter(live);
  const shown = visibleItems(items, hide);
  const mark = MARK_POSTS[kind];
  if (mark !== undefined) {
    return shown.flatMap((item) => unreadPosts(item).filter((post) => postKindOf(post) === mark).map((post) => rowOfPost(item, post, project)));
  }
  if (marked && kind === 'question') return shown.filter((item) => sectionOf(item) === 'question').flatMap((item) => rowOf(item, project, true) ?? []);
  const found = statusSections(items, hide, false).find((one) => one.key === kind);
  return (found?.items ?? []).flatMap((item) => rowOf(item, project, true) ?? []);
}
