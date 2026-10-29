import type { HuddleItem } from './huddle-model';
import { titleOf } from './task-manager-design/task-view';

export interface LockSubtask { id: number; title: string; state: string }
export interface LockBlocker { id: number; kind: string; text: string }
export interface TickLock { subtasks: LockSubtask[]; blockers: LockBlocker[] }

const DONE_STATE = 'done';
const HOLD_KIND = 'children';
export const LOCKED_CODE = 'task_manager_locked';

export function tickLockOf(item: HuddleItem, items: readonly HuddleItem[]): TickLock | null {
  if (item.state === DONE_STATE || item.lane === 'swarm') return null;
  const subtasks = items
    .filter((i) => i.forked_from === item.id && !i.deleted && !i.placeholder && i.state !== DONE_STATE)
    .map((i) => ({ id: i.id, title: titleOf(i), state: i.state }));
  const blockers = (item.blockers ?? []).filter((b) => b.kind !== HOLD_KIND || (b.holding ?? 0) > 0)
    .map((b) => ({ id: b.id, kind: b.kind, text: b.text }));
  return subtasks.length || blockers.length ? { subtasks, blockers } : null;
}

export function lockFromPayload(payload: unknown): TickLock | null {
  const detail = (payload as { detail?: { code?: unknown; blocking?: Partial<TickLock> } } | null)?.detail;
  if (detail?.code !== LOCKED_CODE || !detail.blocking) return null;
  return { subtasks: detail.blocking.subtasks ?? [], blockers: detail.blocking.blockers ?? [] };
}

export function lockReason(lock: TickLock, say: (key: string, args?: Record<string, unknown>) => string): string {
  const parts: string[] = [];
  if (lock.subtasks.length) {
    const names = lock.subtasks.map((s) => say('cplug.huddle.lock.subtask', { title: s.title, state: s.state })).join(', ');
    parts.push(say('cplug.huddle.lock.subtasks', { count: lock.subtasks.length, names }));
  }
  if (lock.blockers.length) {
    const names = lock.blockers.map((b) => (b.kind === HOLD_KIND ? say('cplug.huddle.lock.hold') : b.text || b.kind)).join(', ');
    parts.push(say('cplug.huddle.lock.blockers', { names }));
  }
  return say(`cplug.huddle.refused.${LOCKED_CODE}`, { reason: parts.join('; ') });
}
