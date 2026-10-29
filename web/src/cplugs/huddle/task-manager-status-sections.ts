import { fullMove, moveId, visibleItems, type HuddleItem } from './huddle-model';
import { STATUS_COLOR, STATUS_ICON, statusIconColor, statusOf } from './huddle-status';

export const SECTION_ORDER = ['needs_you', 'question', 'review', 'waiting', 'working', 'scheduled', 'open', 'todo', 'done'] as const;

export type TaskManagerSectionKey = (typeof SECTION_ORDER)[number];

export type TaskManagerViewMode = 'status' | 'area';

export const DEFAULT_FOLDED: readonly TaskManagerSectionKey[] = ['todo', 'done'];

export const SECTION_COLOR: Readonly<Record<TaskManagerSectionKey, string>> = Object.freeze({
  needs_you: STATUS_COLOR.question,
  question: STATUS_COLOR.question,
  working: STATUS_COLOR.working,
  review: STATUS_COLOR.review,
  waiting: STATUS_COLOR.waiting,
  scheduled: STATUS_COLOR.scheduled,
  open: STATUS_COLOR.open,
  todo: STATUS_COLOR.todo,
  done: STATUS_COLOR.done,
});

export const SECTION_ICON: Readonly<Record<TaskManagerSectionKey, string>> = Object.freeze({
  needs_you: STATUS_ICON.question,
  question: STATUS_ICON.question,
  working: STATUS_ICON.working,
  review: STATUS_ICON.review,
  waiting: STATUS_ICON.waiting,
  scheduled: STATUS_ICON.scheduled,
  open: STATUS_ICON.open,
  todo: STATUS_ICON.todo,
  done: STATUS_ICON.done,
});

export const SECTION_ICON_COLOR: Readonly<Record<TaskManagerSectionKey, string>> = Object.freeze({
  needs_you: statusIconColor('question'),
  question: statusIconColor('question'),
  working: statusIconColor('working'),
  review: statusIconColor('review'),
  waiting: statusIconColor('waiting'),
  scheduled: statusIconColor('scheduled'),
  open: statusIconColor('open'),
  todo: statusIconColor('todo'),
  done: statusIconColor('done'),
});

export function sectionOf(item: HuddleItem): TaskManagerSectionKey {
  if (item.needs_you && statusOf(item) !== 'review') return 'needs_you';
  if (item.section && (SECTION_ORDER as readonly string[]).includes(item.section)) return item.section as TaskManagerSectionKey;
  const status = statusOf(item);
  return status;
}

export function statusSectionOf(item: HuddleItem): TaskManagerSectionKey {
  return sectionOf({ ...item, needs_you: false });
}

export function sectionKey(key: TaskManagerSectionKey): string {
  return `cplug.huddle.section.${key}`;
}

export interface StatusSection {
  key: TaskManagerSectionKey;
  all: HuddleItem[];
  items: HuddleItem[];
}

function byPriority(a: HuddleItem, b: HuddleItem): number {
  return a.position - b.position || a.id - b.id;
}

export function statusSections(items: readonly HuddleItem[], hide = false, needsYou = true): StatusSection[] {
  const by = new Map<TaskManagerSectionKey, HuddleItem[]>(SECTION_ORDER.map((k) => [k, []]));
  for (const item of [...items].sort(byPriority)) by.get(needsYou ? sectionOf(item) : statusSectionOf(item))?.push(item);
  return SECTION_ORDER.map((key) => {
    const all = by.get(key) ?? [];
    const items = visibleItems(all, hide);
    return { key, all, items };
  }).filter((s) => s.items.length > 0);
}

/*  hidden  */
export function sectionReorder(items: readonly HuddleItem[], section: StatusSection, from: number, to: number): number[] {
  const order = [...items].sort(byPriority).map((i) => i.id);
  if (from === to) return order;
  const [a, b] = fullMove(section.all.map((i) => i.id), section.items.map((i) => i.id), from, to);
  const sectionOrder = moveId(section.all.map((i) => i.id), a, b);
  const slots = new Set(section.all.map((i) => i.id));
  let next = 0;
  return order.map((id) => (slots.has(id) ? (sectionOrder[next++] as number) : id));
}

export interface AreaSubsection extends StatusSection {
  folded: boolean;
  start: number;
}

export function areaSubsections(items: readonly HuddleItem[], hide: boolean,
  folded: (key: TaskManagerSectionKey) => boolean): { subs: AreaSubsection[]; drawn: HuddleItem[] } {
  const drawn: HuddleItem[] = [];
  const subs = statusSections(items, hide, false).map((section) => {
    const sub: AreaSubsection = { ...section, folded: folded(section.key), start: drawn.length };
    if (!sub.folded) drawn.push(...section.items);
    return sub;
  });
  return { subs, drawn };
}

export function subsectionAt(subs: readonly AreaSubsection[], index: number): AreaSubsection | null {
  return subs.find((s) => !s.folded && index >= s.start && index < s.start + s.items.length) ?? null;
}

export function clampInto(sub: Pick<AreaSubsection, 'start' | 'items'>, index: number): number {
  return Math.min(Math.max(index, sub.start), sub.start + sub.items.length - 1);
}

/*  hidden  */
export const NEEDS_JOE_SECTIONS: readonly TaskManagerSectionKey[] = ['needs_you', 'question', 'review'];

/*  hidden  */
export function withoutSections(items: readonly HuddleItem[], hidden: readonly TaskManagerSectionKey[]): HuddleItem[] {
  return hidden.length === 0 ? (items as HuddleItem[]) : items.filter((item) => !hidden.includes(sectionOf(item)));
}

/*  hidden  */
export function filterChips(items: readonly HuddleItem[], hide: boolean, hidden: readonly TaskManagerSectionKey[],
  extra: Partial<Record<TaskManagerSectionKey, number>> = {}): { key: TaskManagerSectionKey; count: number; hidden: boolean; needs: boolean }[] {
  const counts = new Map<TaskManagerSectionKey, number>(SECTION_ORDER.map((k) => [k, extra[k] ?? 0]));
  for (const item of visibleItems(items, hide)) counts.set(sectionOf(item), (counts.get(sectionOf(item)) ?? 0) + 1);
  return SECTION_ORDER.map((key) => {
    const count = counts.get(key) ?? 0;
    const off = hidden.includes(key);
    return { key, count, hidden: off, needs: off && count > 0 && NEEDS_JOE_SECTIONS.includes(key) };
  });
}
