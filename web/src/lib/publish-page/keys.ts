import type { PublishTab } from '../catalog/menu/route';

export const HELD_REASONS = [
    'signed_out', 'need_handle', 'kind_closed', 'cooldown', 'day_limit', 'open_limit', 'image_limit',
    'not_checked', 'folder_refused', 'version_changed', 'version_exists', 'name_taken', 'name_pending',
    'kind_mismatch', 'rate_limited', 'folder_changed',
] as const;
export type HeldReason = (typeof HELD_REASONS)[number];

export const FAILURE_KEYS = ['limits', 'rules', 'facts', 'appeal', 'withdraw', 'offline', 'session_expired', 'mine_rate_limited'] as const;
export type FailureKey = (typeof FAILURE_KEYS)[number];

export const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'] as const;

export const tabKey = (tab: PublishTab): string => `publish.page.tab.${tab}`;

export const heldKey = (reason: HeldReason): string => `publish.page.held.${reason}`;

export const failureKey = (which: FailureKey): string => `publish.page.failure.${which}`;

export const monthKey = (index: number): string => `publish.page.month.${MONTHS[Math.min(11, Math.max(0, index))]}`;

export const folderKey = (kind: 'skill' | 'theme' | 'mod' | 'plugin'): string => `publish.page.folder.${kind}`;
