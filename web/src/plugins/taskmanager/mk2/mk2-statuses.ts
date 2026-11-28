/* the widget menu */
import { SECTION_ORDER, type TaskManagerSectionKey } from '../task-manager-status-sections';

export type HideableStatus = Exclude<TaskManagerSectionKey, 'done'>;

export const HIDEABLE_STATUSES: readonly HideableStatus[] = SECTION_ORDER.filter((key): key is HideableStatus => key !== 'done');

export const MK2_STATUSES: unique symbol = Symbol('mk2-statuses');

export interface Mk2StatusFilter {
  readonly hidden: readonly TaskManagerSectionKey[];
  showAll(): void;
}

export function isHiddenStatuses(value: unknown): value is HideableStatus[] {
  return Array.isArray(value) && value.every((key, at) => (SECTION_ORDER as readonly unknown[]).includes(key) && value.indexOf(key) === at);
}

export function hideableStatuses(stored: readonly TaskManagerSectionKey[]): HideableStatus[] {
  return HIDEABLE_STATUSES.filter((key) => stored.includes(key));
}

export function withStatusShown(hidden: readonly TaskManagerSectionKey[], key: HideableStatus, shown: boolean): HideableStatus[] {
  return HIDEABLE_STATUSES.filter((one) => (one === key ? !shown : hidden.includes(one)));
}
