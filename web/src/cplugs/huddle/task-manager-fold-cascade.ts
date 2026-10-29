import type { Attachment } from 'svelte/attachments';
import { watchCascadeHint } from '../sdk/ui';
import type { HuddleItem, TaskManagerItemGroup } from './huddle-model';
import { sectionsOf } from './huddle-model';
import { areaSubsections, statusSections, type TaskManagerViewMode, type StatusSection } from './task-manager-status-sections';
import { sectionAreas } from './task-manager-status-areas';
import { setGroupsFolded } from './task-manager-groups.svelte';
import { sectionFoldKey, setSectionsFolded, statusSubFoldKey, subFoldKey } from './task-manager-status-folds.svelte';

export function keepShiftOffSelection(event: MouseEvent): void {
  if (event.shiftKey) event.preventDefault();
}

export function cascadeCue(): Attachment<HTMLElement> {
  return (node) => watchCascadeHint(node);
}

export interface FoldTargets {
  keys: string[];
  groups: TaskManagerItemGroup[];
}

export function underStatusSection(list: string, section: StatusSection, groups: readonly TaskManagerItemGroup[]): string[] {
  const { subs, headed } = sectionAreas(section, groups, () => false);
  return headed ? subs.map((sub) => statusSubFoldKey(sub.area, section.key, list)) : [];
}

export function underArea(area: number | null, items: readonly HuddleItem[], hide: boolean): string[] {
  return areaSubsections(items, hide, () => false).subs.map((sub) => subFoldKey(area, sub.key));
}

export function underProject(view: TaskManagerViewMode, list: string, items: readonly HuddleItem[],
  groups: readonly TaskManagerItemGroup[], hide: boolean): FoldTargets {
  if (view === 'area') {
    const sections = sectionsOf(items, groups);
    return {
      keys: sections.flatMap((s) => underArea(s.group?.id ?? null, s.items, hide)),
      groups: sections.flatMap((s) => (s.group ? [s.group] : [])),
    };
  }
  return {
    keys: statusSections(items, hide).flatMap((s) => [sectionFoldKey(list, s.key), ...underStatusSection(list, s, groups)]),
    groups: [],
  };
}

export function foldAll(targets: FoldTargets, folded: boolean): void {
  setSectionsFolded(targets.keys, folded);
  void setGroupsFolded(targets.groups, folded);
}
