import { t } from '../sdk';
import { SECTION_ICON, SECTION_ICON_COLOR, SECTION_ORDER, sectionKey, type TaskManagerSectionKey } from './task-manager-status-sections';
import { KIND_COLORS, POST_KINDS } from './task-manager-posts';
import type { WaitingKind, WaitingMark } from './task-manager-waiting';

export type TailKind = WaitingKind | TaskManagerSectionKey;

export const TAIL_COUNT_MAX = 99;

export const TAIL_ORDER: readonly TailKind[] = Object.freeze([
  'question', 'info', ...SECTION_ORDER.filter((key) => key !== 'question'),
]);

export interface TailBadge {
  kind: TailKind;
  count: number;
  icon: string;
  color: string;
  title: string;
}

export function marksToBadges(marks: readonly WaitingMark[]): TailBadge[] {
  return marks.map((mark) => ({ kind: mark.kind, count: mark.count, icon: mark.icon, color: mark.color, title: t(mark.titleKey, { count: mark.count }) }));
}

export function chipsToBadges(chips: readonly { key: TaskManagerSectionKey; count: number }[]): TailBadge[] {
  return chips.filter((chip) => chip.count > 0).map((chip) => ({
    kind: chip.key, count: chip.count, icon: SECTION_ICON[chip.key], color: SECTION_ICON_COLOR[chip.key], title: `${t(sectionKey(chip.key))}: ${chip.count}`,
  }));
}

export function kindsPresent(lists: readonly (readonly TailBadge[])[]): TailKind[] {
  const seen = new Set<TailKind>(lists.flatMap((list) => list.map((badge) => badge.kind)));
  return TAIL_ORDER.filter((kind) => seen.has(kind));
}

export function projectBadges(folded: boolean, marks: readonly WaitingMark[], chips: readonly { key: TaskManagerSectionKey; count: number }[]): TailBadge[] {
  return [...(folded ? marksToBadges(marks) : []), ...chipsToBadges(folded ? chips.filter((chip) => chip.key !== 'question') : chips)];
}

export function tailKindLook(kind: TailKind): { icon: string; color: string } {
  if (kind === 'info') return { icon: POST_KINDS.info.icon, color: POST_KINDS.info.color };
  if (kind === 'question') return { icon: SECTION_ICON.question, color: KIND_COLORS.question.color };
  return { icon: SECTION_ICON[kind], color: SECTION_ICON_COLOR[kind] };
}
