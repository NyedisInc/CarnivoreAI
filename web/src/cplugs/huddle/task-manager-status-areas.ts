import { sectionIndex, type HuddleItem, type TaskManagerItemGroup } from './huddle-model';
import type { TaskManagerSectionKey, StatusSection } from './task-manager-status-sections';

export interface SectionArea extends StatusSection {
  area: number | null;
  name: string | null;
  folded: boolean;
  start: number;
}

function areaIdOf(item: HuddleItem, known: ReadonlySet<number>): number | null {
  return item.group != null && known.has(item.group) ? item.group : null;
}

export function sectionAreas(section: StatusSection, groups: readonly TaskManagerItemGroup[],
  folded: (key: TaskManagerSectionKey, area: number | null) => boolean): { subs: SectionArea[]; headed: boolean; drawn: HuddleItem[] } {
  const ordered = [...groups].sort((a, b) => a.position - b.position || a.id - b.id);
  const known = new Set(ordered.map((g) => g.id));
  const slots: { area: number | null; name: string | null }[] = [
    ...ordered.map((g) => ({ area: g.id as number | null, name: g.name as string | null })),
    { area: null, name: null },
  ];
  const drawn: HuddleItem[] = [];
  const subs: SectionArea[] = [];
  for (const slot of slots) {
    const items = section.items.filter((i) => areaIdOf(i, known) === slot.area);
    if (!items.length) continue;
    const isFolded = folded(section.key, slot.area);
    subs.push({ key: section.key, all: section.all.filter((i) => areaIdOf(i, known) === slot.area), items, area: slot.area,
      name: slot.name, folded: isFolded, start: drawn.length });
    if (!isFolded) drawn.push(...items);
  }
  return { subs, headed: ordered.length > 0, drawn };
}

export function areaDropIndex(items: readonly HuddleItem[], groups: readonly TaskManagerItemGroup[], moved: number,
  area: number | null, visible: readonly number[], at: number): number {
  const known = new Set(groups.map((g) => g.id));
  const all = [...items].filter((i) => i.id !== moved && areaIdOf(i, known) === area)
    .sort((a, b) => a.position - b.position || a.id - b.id).map((i) => i.id);
  return sectionIndex(all, visible, at);
}
