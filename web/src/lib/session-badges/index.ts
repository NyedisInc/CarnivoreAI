import { registerBadgeSource, SLOT_MAX_ITEMS } from './slot';
import { prBadges } from './pr';
import { progressBadges } from './progress.svelte';
import { jobsBadges } from '../pack-jobs/jobs-badge';
import { pluginBadges } from './plugin-badges';

registerBadgeSource('progress', progressBadges, 1);
registerBadgeSource('pr', prBadges, 1);
registerBadgeSource('jobs', (row) => jobsBadges(row), 1);
registerBadgeSource('plugin', pluginBadges, SLOT_MAX_ITEMS);

export { badgeSlotPlan, registerBadgeSource, BADGE_ORDER, SLOT_MAX_ITEMS } from './slot';
export type { BadgeItem, BadgeKind, BadgeSlotPlan, BadgeSource } from './slot';
export { bellLit, progressFor, progressLabel } from './progress.svelte';
export type { Progress } from './progress.svelte';
