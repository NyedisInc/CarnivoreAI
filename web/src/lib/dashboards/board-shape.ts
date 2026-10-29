import type { Layout, SlotId } from '../../opscenter/engine/types';

export const FLEX_ROW_PX = 360;

export const MIN_ROW_SHARE = 0.06;

export interface ShapeBox {
  id: SlotId;
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface BoardShape {
  boxes: ShapeBox[];
  rows: number;
  widgets: number;
}

export function boardShape(layout: Layout | undefined): BoardShape {
  const rows = (layout?.rows ?? []).filter((row) => row.slots.length > 0);
  if (rows.length === 0) return { boxes: [], rows: 0, widgets: 0 };
  const weights = rows.map((row) => Math.max(1, row.kind === 'px' ? row.size : row.size * FLEX_ROW_PX));
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  const shares = weights.map((weight) => Math.max(MIN_ROW_SHARE, weight / total));
  const scale = shares.reduce((sum, share) => sum + share, 0);
  const boxes: ShapeBox[] = [];
  let top = 0;
  rows.forEach((row, index) => {
    const height = (shares[index]! / scale) * 100;
    const frs = row.slots.map((slot) => Math.max(0, slot.fr));
    const sum = frs.reduce((acc, fr) => acc + fr, 0);
    let left = 0;
    row.slots.forEach((slot, at) => {
      const width = (sum > 0 ? frs[at]! / sum : 1 / row.slots.length) * 100;
      boxes.push({ id: slot.id, left, top, width, height });
      left += width;
    });
    top += height;
  });
  return { boxes, rows: rows.length, widgets: boxes.length };
}
