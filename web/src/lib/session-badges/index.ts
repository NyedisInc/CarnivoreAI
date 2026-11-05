import { registerBadgeSource } from './slot';
import { prBadges } from './pr';
import { progressBadges } from './progress.svelte';

registerBadgeSource('progress', progressBadges, 1);
registerBadgeSource('pr', prBadges, 1);

export { badgeSlotPlan, registerBadgeSource, BADGE_ORDER, SLOT_MAX_ITEMS } from './slot';
export type { BadgeItem, BadgeKind, BadgeSlotPlan, BadgeSource } from './slot';
export { bellLit, progressFor, progressLabel } from './progress.svelte';
export type { Progress } from './progress.svelte';
