import { t } from '../sdk';
import { BADGE_STATUSES, taskManagerPrefs, setBadgeStatus, type BadgeStatus } from './task-manager-prefs.svelte';

export interface BadgeMenuNode {
  id: string;
  label: string;
  checked: boolean;
  toggle: true;
  run: () => void;
}

export function badgeLabelKey(status: BadgeStatus): string {
  return `cplug.huddle.badge_menu.${status}`;
}

export const TASK_MANAGER_BADGE_HEADING = 'cplug.huddle.badge_menu.heading';

/* label: ' */
export function taskManagerBadgeNodes(): BadgeMenuNode[] {
  return BADGE_STATUSES.map((status) => ({
    id: status,
    label: t(badgeLabelKey(status)),
    checked: taskManagerPrefs.badge[status],
    toggle: true,
    run: () => void setBadgeStatus(status, !taskManagerPrefs.badge[status]),
  }));
}

export const taskManagerBadgeMenu = { headingKey: TASK_MANAGER_BADGE_HEADING, nodes: taskManagerBadgeNodes };
