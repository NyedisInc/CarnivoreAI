import type { TaskManagerDeltaWire } from '../sdk/task-manager-delta';
import type { BoardListRow } from './board-model';

export const SHARED_LIST = 'all';
const TASK_DONE = 'done';

export function shownTaskIds(boards: readonly BoardListRow[]): Set<number> {
  const ids = new Set<number>();
  for (const board of boards) if (board.task && typeof board.task.item_id === 'number') ids.add(board.task.item_id);
  return ids;
}

export function closedReviewsMoved(delta: TaskManagerDeltaWire, key: string, shown: ReadonlySet<number>, doneSeen: Set<number>): boolean {
  let moved = false;
  for (const entry of delta.lists ?? []) {
    if (entry.deleted.some((id) => shown.has(id))) moved = true;
    const ours = entry.list === key || entry.list === SHARED_LIST;
    for (const item of entry.items) {
      if (shown.has(item.id)) moved = true;
      if (item.state !== TASK_DONE) {
        doneSeen.delete(item.id);
      } else if (ours && !doneSeen.has(item.id)) {
        doneSeen.add(item.id);
        moved = true;
      }
    }
  }
  return moved;
}
