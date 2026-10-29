/* and writes nothing */
import type { HuddleItem, TaskManagerItemGroup } from './huddle-model';
import type { FoldTargets } from './task-manager-fold-cascade';
import { statusSections, type TaskManagerViewMode } from './task-manager-status-sections';
import { projectFoldKey, sectionFoldKey, statusSubFoldKey, subFoldKey } from './task-manager-status-folds.svelte';

export function foldsHiding(view: TaskManagerViewMode, list: string, item: HuddleItem, items: readonly HuddleItem[],
  groups: readonly TaskManagerItemGroup[], hide: boolean): FoldTargets {
  const keys = [projectFoldKey(list)];
  const named = item.group === null || item.group === undefined ? null : (groups.find((g) => g.id === item.group) ?? null);
  if (view === 'area') {
    const area = named?.id ?? null;
    const inArea = items.filter((i) => (i.group ?? null) === area);
    const sub = statusSections(inArea, hide, false).find((s) => s.items.some((i) => i.id === item.id));
    if (sub) keys.push(subFoldKey(area, sub.key));
    return { keys, groups: named ? [named] : [] };
  }
  const section = statusSections(items, hide).find((s) => s.items.some((i) => i.id === item.id));
  if (section) {
    keys.push(sectionFoldKey(list, section.key));
    if (groups.length > 0) keys.push(statusSubFoldKey(named?.id ?? null, section.key, list));
  }
  return { keys, groups: [] };
}
