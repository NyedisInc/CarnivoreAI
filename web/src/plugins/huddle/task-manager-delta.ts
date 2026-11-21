import { isAgentList, type HuddleItem, type TaskManagerInboxEntry, type TaskManagerItemGroup, type TaskManagerListBody, type TaskManagerListRow, type TaskManagerGroup } from './huddle-model';
import type { TaskManagerDeltaOf, TaskManagerListDeltaOf } from '../sdk/task-manager-delta';

export type TaskManagerListDelta = TaskManagerListDeltaOf<HuddleItem, TaskManagerItemGroup, TaskManagerInboxEntry>;

export type TaskManagerDelta = TaskManagerDeltaOf<TaskManagerListDelta, TaskManagerListRow>;

export type DeltaLane = 'lists' | 'aggregate' | 'body';

export interface DeltaApplied<T> {
  value: T;
  changed: boolean;
  missing: boolean;
}

export function hidesSwarm(list: string, includeSwarm: boolean): boolean {
  return !includeSwarm && !isAgentList(list);
}

export function viewDoneCount(entry: TaskManagerListDelta, includeSwarm: boolean): number | null {
  if (typeof entry.done_count !== 'number') return null;
  return entry.done_count - (hidesSwarm(entry.list, includeSwarm) ? entry.done_swarm ?? 0 : 0);
}

function withDoneCount<T extends { done_count?: number }>(target: T, done: number | null): T {
  return done === null ? target : { ...target, done_count: done };
}

export function applyListItems(items: readonly HuddleItem[], delta: TaskManagerListDelta, includeSwarm: boolean): DeltaApplied<HuddleItem[]> {
  const fresh = new Map(delta.items.map((item) => [item.id, item]));
  const held = new Map(items.map((item) => [item.id, item]));
  const hidden = hidesSwarm(delta.list, includeSwarm) ? new Set(delta.swarm ?? []) : new Set<number>();
  const value: HuddleItem[] = [];
  let missing = false;
  let changed = fresh.size > 0 || delta.deleted.some((id) => held.has(id));
  for (const id of delta.order) {
    if (hidden.has(id)) continue;
    const row = fresh.get(id) ?? held.get(id);
    if (!row) {
      missing = true;
      continue;
    }
    const number = delta.numbers[String(id)] ?? null;
    if (fresh.has(id) || (row.number ?? null) === number) {
      value.push(row);
    } else {
      value.push({ ...row, number });
      changed = true;
    }
  }
  if (value.length !== items.length || value.some((row, at) => row !== items[at])) changed = true;
  return { value, changed, missing };
}

function withInbox<T extends { inbox?: TaskManagerInboxEntry[] }>(target: T, inbox: TaskManagerInboxEntry[] | null): T {
  const out = { ...target };
  if (inbox && inbox.length) out.inbox = inbox;
  else delete out.inbox;
  return out;
}

export function applyToBody(body: TaskManagerListBody, delta: TaskManagerDelta, includeSwarm: boolean): DeltaApplied<TaskManagerListBody> {
  const entry = delta.lists?.find((e) => e.list === body.list);
  if (!entry) return { value: body, changed: false, missing: false };
  const items = applyListItems(body.items, entry, includeSwarm);
  const value = withDoneCount(withInbox({ ...body, revision: entry.revision, groups: entry.groups, items: items.value }, entry.inbox),
    viewDoneCount(entry, includeSwarm));
  return { value, changed: true, missing: items.missing };
}

export function applyToGroups(groups: readonly TaskManagerGroup[], delta: TaskManagerDelta): DeltaApplied<TaskManagerGroup[]> {
  let value = [...groups];
  let changed = false;
  let missing = false;
  for (const entry of delta.lists ?? []) {
    const at = value.findIndex((g) => g.list === entry.list);
    const hidden = hidesSwarm(entry.list, false) ? new Set(entry.swarm ?? []) : new Set<number>();
    const done = viewDoneCount(entry, false);
    const shows = entry.order.some((id) => !hidden.has(id)) || entry.groups.length > 0 || Boolean(entry.inbox?.length) || (done ?? 0) > 0;
    if (at < 0) {
      missing = missing || shows;
      continue;
    }
    changed = true;
    if (!shows) {
      value = value.filter((_, i) => i !== at);
      continue;
    }
    const group = value[at] as TaskManagerGroup;
    const items = applyListItems(group.items, entry, false);
    missing = missing || items.missing;
    value[at] = withDoneCount(withInbox({ ...group, revision: entry.revision, groups: entry.groups, items: items.value }, entry.inbox), done);
  }
  return { value: changed ? value : [...groups], changed, missing };
}
