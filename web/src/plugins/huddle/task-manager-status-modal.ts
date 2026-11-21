import { SECTION_ORDER, type TaskManagerSectionKey } from './task-manager-status-sections';
import type { TailKind } from './task-manager-tail-slots';

export type BadgeAction = 'modal' | 'filter' | null;

export function badgeAction(kind: TailKind): BadgeAction {
  if (kind === 'info') return 'modal';
  if (kind === 'needs_you') return null;
  return (SECTION_ORDER as readonly string[]).includes(kind) ? 'filter' : null;
}

export function isClickable(kind: TailKind): boolean {
  return badgeAction(kind) !== null;
}

export function statusOfBadge(kind: TailKind): TaskManagerSectionKey {
  return kind as TaskManagerSectionKey;
}
