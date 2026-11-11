
import { cellOf, landColumnOrRow, landSeam, landSplit, neighboursAt, type ColumnDrop } from './column';
import { settleDrop } from './compact';
import type { DropTarget } from './layout.svelte';
import { META } from './meta';
import { moveCellToNewRow, rowOf } from './model';
import { placeOf, spanOf, visualOrder } from './spans';
import { stackCell } from './stack';
import type { Layout, MetaMap, RowId, SlotId } from './types';

interface Landing {
  layout: Layout;
  rows: RowId[];
}

function rawLanding(layout: Layout, id: SlotId, target: DropTarget, metas: MetaMap): Layout {
  switch (target.kind) {
    case 'row':
      return landColumnOrRow(layout, id, target.row, target.index);
    case 'column':
      return landColumnOrRow(layout, id, target.at, target.index);
    case 'stack':
      return stackCell(layout, id, target.of, target.edge, metas, target.width, target.height);
    case 'stack-run':
      return stackCell(layout, id, target.of, target.edge, metas);
    case 'split':
      return landSplit(layout, id, target.of, target.side, target.width, metas, target.height);
    case 'seam':
      return landSeam(layout, id, target.rows, target.width, metas, target.height);
    default:
      return moveCellToNewRow(layout, id, target.after, metas);
  }
}

export function landing(layout: Layout, id: SlotId, target: DropTarget, metas: MetaMap = META): Landing | null {
  const raw = rawLanding(layout, id, target, metas);
  if (raw === layout) return null;
  const settled = settleDrop(layout, raw, id, metas);
  if (!settled) return null;
  const place = placeOf(settled.layout, id);
  const home = place ? settled.layout.rows[place.rowAt] : undefined;
  const slot = home?.slots[place!.slotAt];
  if (!place || !slot) return null;
  const covered: RowId[] = [];
  for (let step = 0; step < spanOf(slot); step += 1) {
    const row = settled.layout.rows[place.rowAt + step];
    if (row) covered.push(...(settled.covers.get(row.id) ?? [row.id]));
  }
  return { layout: settled.layout, rows: covered };
}

export function applyDrop(layout: Layout, id: SlotId, target: DropTarget, metas: MetaMap = META): Layout {
  return landing(layout, id, target, metas)?.layout ?? layout;
}

export function columnDropAt(layout: Layout, rowId: RowId, index: number, dragged: SlotId): ColumnDrop | null {
  const row = rowOf(layout, rowId);
  if (!row) return null;
  const landed = landing(layout, dragged, { kind: 'row', row: rowId, index });
  if (!landed) return null;
  const drawnAt = landed.rows.map((one) => layout.rows.findIndex((each) => each.id === one)).filter((at) => at >= 0);
  if (drawnAt.length === 0) return null;
  const first = Math.min(...drawnAt);
  const last = Math.max(...drawnAt);
  if (last === first) return null;
  const { left, right } = neighboursAt(row, index, dragged);
  return { kind: 'column', row: layout.rows[first]!.id, rows: last - first + 1, at: rowId, index, left, right };
}

export function moveCellToColumn(layout: Layout, id: SlotId, left: SlotId, right: SlotId): Layout {
  if (id === left || id === right) return layout;
  const place = placeOf(layout, left);
  const row = place ? layout.rows[place.rowAt] : undefined;
  if (!row) return layout;
  const order = visualOrder(row);
  const index = order.findIndex((entry) => cellOf(entry) === left) + 1;
  if (neighboursAt(row, index, id).right !== right) return layout;
  return applyDrop(layout, id, { kind: 'row', row: row.id, index });
}
