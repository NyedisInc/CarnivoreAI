import type { SlotId } from '../engine/types';
import type { RowModel } from '../engine/types';
import { colsFor } from './dash-adapter';
import { layoutFor, resolveGrid } from './grid-data';

export interface RectBox {
  id: SlotId;
  left: number;
  top: number;
  width: number;
  height: number;
}

export function boardRects(blob: { rows?: RowModel[]; grid?: unknown } | undefined, width: number): RectBox[] {
  const rows = (blob?.rows ?? []).filter((row) => row.slots.length > 0);
  if (rows.length === 0) return [];
  const cols = colsFor(width);
  const items = layoutFor(resolveGrid({ rows: blob!.rows!, grid: blob?.grid }, blob!.rows!), cols);
  const bottom = Math.max(1, ...items.map((i) => i.y + i.h));
  return items.map((i) => ({
    id: i.id,
    left: (i.x / cols) * 100,
    top: (i.y / bottom) * 100,
    width: (i.w / cols) * 100,
    height: (i.h / bottom) * 100,
  }));
}
