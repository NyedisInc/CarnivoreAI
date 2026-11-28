import { t, type MenuNode, type PluginMenu } from '../sdk';
import { ALL_LIST, AGGREGATE, isApproved, listFallback, moveTargets, type HuddleItem, type TaskManagerListRow } from './huddle-model';
import { huddle, moveToList, setBackBurner } from './huddle.svelte';
import { groupsOf, setItemGroup } from './task-manager-groups.svelte';
import { requestEdit } from './task-manager-edit-request.svelte';
import { openScheduleEditor } from './task-manager-schedule-editor.svelte';
import { openFork } from './task-manager-fork.svelte';

export function listName(listKey: string, name: string | null): string {
  if (listKey === ALL_LIST) return t('cplug.huddle.list.shared');
  if (name) return name;
  const fallback = listFallback(listKey);
  return t(fallback.key, { id: fallback.id });
}

function moveBranch(item: HuddleItem): MenuNode {
  const current = item.group ?? null;
  const rows: TaskManagerListRow[] = huddle.lists.filter((row) => row.key !== AGGREGATE);
  const choose = (row: TaskManagerListRow): MenuNode => {
    const here = row.key === item.list && current === null;
    return {
      id: `move-to:${row.key}`, label: listName(row.key, row.name), checked: here,
      run: here ? () => {} : () => void (row.key === item.list ? setItemGroup(item, null) : moveToList(item, row.key)),
    };
  };
  const children = rows.flatMap((row): MenuNode[] => {
    const groups = groupsOf(row.key);
    const own = row.key === item.list;
    const entries: MenuNode[] = groups.map((group) => ({
      id: `move-group:${row.key}:${group.id}`, label: group.name, checked: own && group.id === current,
      run: own && group.id === current ? () => {} : () => void (own ? setItemGroup(item, group.id) : moveToList(item, row.key, group.id)),
    }));
    return groups.length === 0 ? [choose(row)] : [{ id: `move-list:${row.key}`, label: listName(row.key, row.name), children: [choose(row), ...entries] }];
  });
  return { id: 'move-to', label: t('cplug.huddle.move.title'), children };
}

export function taskRowMenu(item: HuddleItem): PluginMenu {
  const parked = item.state === 'todo';
  const nodes: MenuNode[] = [];
  if (moveTargets(huddle.lists, item.list).length > 0 || groupsOf(item.list).length > 0) nodes.push(moveBranch(item));
  nodes.push({ id: 'back-burner', label: t(parked ? 'cplug.huddle.move.take_off_back_burner' : 'cplug.huddle.move.back_burner'), run: () => void setBackBurner(item, !parked) });
  if (!isApproved(item.state)) nodes.push({ id: 'schedule', label: t('cplug.huddle.move.schedule'), run: () => openScheduleEditor(item.list, item) });
  nodes.push({ id: 'fork', label: t('cplug.huddle.move.fork'), run: () => openFork(item) });
  nodes.push({ id: 'title', label: t('cplug.huddle.move.title_edit'), run: () => requestEdit('title', item.id) });
  return { label: t('cplug.huddle.move.title'), nodes };
}
