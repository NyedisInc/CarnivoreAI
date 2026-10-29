
import { applyDrop } from '../engine/drop';
import type { DropTarget } from '../engine/layout.svelte';
import { META } from '../engine/meta';
import { showCell } from '../engine/model';
import { visualOrder } from '../engine/spans';
import type { Layout, MetaMap, SlotId } from '../engine/types';

export interface ShowAtResult {
  layout: Layout;
  landed: boolean;
}

function drawnAt(layout: Layout, rowId: string, id: SlotId): number {
  const row = layout.rows.find((one) => one.id === rowId);
  if (!row) return -1;
  return visualOrder(row).findIndex((cell) => cell.kind === 'slot' && cell.slot.id === id);
}

export function aimWithArrival(shown: Layout, id: SlotId, target: DropTarget): DropTarget {
  if (target.kind !== 'row') return target;
  const at = drawnAt(shown, target.row, id);
  if (at < 0 || at >= target.index) return target;
  return { ...target, index: target.index + 1 };
}

export function showAt(layout: Layout, id: SlotId, target: DropTarget, metas: MetaMap = META): ShowAtResult {
  const shown = showCell(layout, id, metas);
  if (shown === layout) return { layout, landed: false };
  const dropped = applyDrop(shown, id, aimWithArrival(shown, id, target), metas);
  return dropped === shown ? { layout: shown, landed: false } : { layout: dropped, landed: true };
}
