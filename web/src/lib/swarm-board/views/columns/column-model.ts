import type { CardColumn, CardView } from '../../board-types';
import type { BoardLane } from '../../board-data.svelte';
import { beforeIdAt } from '../../card-actions.svelte';
import { cellCards } from '../swimlanes/lane-model';

export const STACK_ORDER: readonly CardColumn[] = ['review', 'in_progress', 'todo', 'done'];

export interface StackGroup {
  column: CardColumn;
  shown: CardView[];
  more: number;
}

export function stack(lane: Pick<BoardLane, 'columns' | 'counts'>, open: Partial<Record<CardColumn, boolean>>): StackGroup[] {
  return STACK_ORDER.map((column) => ({ column, ...cellCards(lane.columns[column] ?? [], lane.counts[column] ?? 0, !!open[column]) }))
    .filter((g) => g.shown.length > 0 || g.more > 0);
}

export function dropBefore(drawn: readonly CardView[], full: readonly CardView[], card: CardView, index: number): number | null {
  const above = drawn.slice(0, Math.max(0, index)).filter((c) => c.column === card.column).length;
  return beforeIdAt(full, card.id, above, card.list_key);
}
