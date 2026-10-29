import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';
import { NEEDS_JOE_SECTIONS, sectionOf } from '../../../cplugs/huddle/task-manager-status-sections';
import { isUnreadItem, unreadMessageCount } from './mk2-unread';
import type { ViewChip } from '../../../cplugs/huddle/task-manager-view-filter.svelte';

export const MK2_CHIP_ORDER = ['all', 'needs_you', 'unread', 'scheduled'] as const;
export type Mk2ChipId = (typeof MK2_CHIP_ORDER)[number];

export const MK2_CHIP_LABEL: Readonly<Record<Mk2ChipId, string>> = Object.freeze({
  all: 'opscenter.cell.task_manager_mk2.chip.all',
  needs_you: 'cplug.huddle.section.needs_you',
  unread: 'opscenter.cell.task_manager_mk2.chip.unread',
  scheduled: 'cplug.huddle.section.scheduled',
});

export const MK2_CHIP_ICON: Readonly<Record<Mk2ChipId, string>> = Object.freeze({
  all: 'list',
  needs_you: 'status-question',
  unread: 'bell',
  scheduled: 'status-scheduled',
});

export type Mk2ChipMode = 'full' | 'count' | 'icon';

const CHIP_DIGIT_PX = 7;
const COUNTED_CHIPS = 3;
const CHIP_GAPS_PX = 12;
const BAR_PADDING_PX = 16;
const FULL_ROW_PX = 314 + COUNTED_CHIPS * CHIP_DIGIT_PX + CHIP_GAPS_PX + BAR_PADDING_PX;
const COUNT_ROW_PX = 200 + COUNTED_CHIPS * CHIP_DIGIT_PX + CHIP_GAPS_PX + BAR_PADDING_PX;

export const MK2_CHIPS_ICON_BELOW_PX = COUNT_ROW_PX;

export const MK2_CHIPS_FULL_FROM_PX = FULL_ROW_PX;

export function chipMode(width: number): Mk2ChipMode {
  if (!(width > 0) || width >= MK2_CHIPS_FULL_FROM_PX) return 'full';
  return width >= MK2_CHIPS_ICON_BELOW_PX ? 'count' : 'icon';
}

export function isUnreadTask(item: HuddleItem): boolean {
  return isUnreadItem(item);
}

export function unreadCount(items: readonly HuddleItem[]): number {
  return items.reduce((sum, item) => sum + unreadMessageCount(item), 0);
}

export const MK2_CHIP_TEST: Readonly<Record<ViewChip, (item: HuddleItem) => boolean>> = Object.freeze({
  needs_you: (item: HuddleItem) => NEEDS_JOE_SECTIONS.includes(sectionOf(item)),
  unread: isUnreadTask,
  scheduled: (item: HuddleItem) => sectionOf(item) === 'scheduled',
});

export function chipCount(chip: ViewChip, items: readonly HuddleItem[]): number {
  return chip === 'unread' ? unreadCount(items) : items.filter(MK2_CHIP_TEST[chip]).length;
}
