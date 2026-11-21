import { authFetch } from '../sdk';
import { huddle, write } from './huddle.svelte';
import { regroup, type HuddleItem, type TaskManagerItemGroup } from './huddle-model';

function seg(key: string): string {
  return encodeURIComponent(key);
}

export function groupsOf(list: string): TaskManagerItemGroup[] {
  const found = huddle.body?.list === list ? huddle.body.groups : huddle.groups?.find((g) => g.list === list)?.groups;
  return [...(found ?? [])].sort((a, b) => a.position - b.position || a.id - b.id);
}

export function createGroup(list: string, name: string): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/lists/${seg(list)}/groups`, { method: 'POST', body: JSON.stringify({ name }) }));
}

export function renameGroup(group: TaskManagerItemGroup, name: string): Promise<boolean> {
  const clean = name.trim();
  if (!clean || clean === group.name) return Promise.resolve(true);
  return write(() => authFetch(`/cplugs/huddle/groups/${group.id}`, { method: 'PATCH', body: JSON.stringify({ name: clean }) }));
}

export function moveGroup(group: TaskManagerItemGroup, position: number): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/groups/${group.id}`, { method: 'PATCH', body: JSON.stringify({ position }) }));
}

export function removeGroup(group: TaskManagerItemGroup): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/groups/${group.id}`, { method: 'DELETE' }));
}

function patchGroups(list: string, change: (groups: TaskManagerItemGroup[]) => TaskManagerItemGroup[]): void {
  if (huddle.body?.list === list) huddle.body = { ...huddle.body, groups: change(huddle.body.groups ?? []) };
  if (huddle.groups) huddle.groups = huddle.groups.map((g) => (g.list === list ? { ...g, groups: change(g.groups ?? []) } : g));
}

function patchItems(list: string, change: (items: HuddleItem[]) => HuddleItem[]): void {
  if (huddle.body?.list === list) huddle.body = { ...huddle.body, items: change(huddle.body.items) };
  if (huddle.groups) huddle.groups = huddle.groups.map((g) => (g.list === list ? { ...g, items: change(g.items) } : g));
}

export function setFolded(group: TaskManagerItemGroup, folded: boolean): Promise<boolean> {
  patchGroups(group.list, (all) => all.map((g) => (g.id === group.id ? { ...g, folded } : g)));
  return write(() => authFetch(`/cplugs/huddle/groups/${group.id}`, { method: 'PATCH', body: JSON.stringify({ folded }) }));
}

export function setGroupsFolded(groups: readonly TaskManagerItemGroup[], folded: boolean): Promise<boolean> {
  if (!groups.length) return Promise.resolve(true);
  const ids = new Set(groups.map((g) => g.id));
  for (const list of new Set(groups.map((g) => g.list))) {
    patchGroups(list, (all) => all.map((g) => (ids.has(g.id) ? { ...g, folded } : g)));
  }
  return write(() => authFetch('/cplugs/huddle/groups/fold', { method: 'POST', body: JSON.stringify({ ids: [...ids], folded }) }));
}

export function setItemGroup(item: HuddleItem, group: number | null, index: number | null = null): Promise<boolean> {
  patchItems(item.list, (items) => regroup(items, groupsOf(item.list), item.id, group, index));
  const body: Record<string, unknown> = { group, expected_revision: item.revision };
  if (index !== null) body.index = index;
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}/group`, { method: 'POST', body: JSON.stringify(body) }));
}
