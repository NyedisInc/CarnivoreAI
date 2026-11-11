import type { Layout, SlotId } from '../../opscenter/engine/types';
import { boardRects } from '../../opscenter/dashgrid/board-rects';
import { NOMINAL_WIDTH } from '../../opscenter/dashgrid/format/convert-v6';

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
  const rows = (layout?.rows ?? []).filter((row) => row.slots.length > 0).length;
  const boxes = boardRects(layout, NOMINAL_WIDTH);
  return { boxes, rows, widgets: boxes.length };
}
