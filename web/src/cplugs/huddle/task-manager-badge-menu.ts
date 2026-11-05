/* is gone with */
import type { BadgeStatus } from './task-manager-prefs.svelte';

export function badgeLabelKey(status: BadgeStatus): string {
  return `cplug.huddle.badge_menu.${status}`;
}
