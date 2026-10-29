
import { moveCell, normalizeRow, rowOf, rowOfCell, withoutCell } from './model';
import { clearSpan, placeOf, repairSpans, spanOf, visualOrder, type VisualCell } from './spans';
import type { Layout, RowId, RowModel, Slot, SlotId } from './types';

export interface ColumnDrop {
  kind: 'column';
  row: RowId;
  rows: number;
  at: RowId;
  index: number;
  left: SlotId | null;
  right: SlotId | null;
}

export function cellOf(entry: VisualCell | undefined): SlotId | null {
  if (!entry) return null;
  return entry.kind === 'slot' ? entry.slot.id : entry.of;
}

export function neighboursAt(row: RowModel, index: number, dragged: SlotId): { left: SlotId | null; right: SlotId | null } {
  const order = visualOrder(row);
  let before = index - 1;
  while (before >= 0 && cellOf(order[before]) === dragged) before -= 1;
  let after = index;
  while (after < order.length && cellOf(order[after]) === dragged) after += 1;
  return { left: cellOf(order[before]), right: cellOf(order[after]) };
}

function rowsOf(layout: Layout, id: SlotId): [number, number] | null {
  const place = placeOf(layout, id);
  if (!place) return null;
  const slot = layout.rows[place.rowAt]?.slots[place.slotAt];
  return slot ? [place.rowAt, place.rowAt + Math.min(spanOf(slot), layout.rows.length - place.rowAt) - 1] : null;
}

function lift(layout: Layout, id: SlotId): { base: Layout; moving: Slot; from: RowId; share: number } | null {
  const cleared = clearSpan(layout, id);
  const from = rowOfCell(cleared, id);
  const moving = from?.slots.find((slot) => slot.id === id);
  if (!from || !moving) return null;
  const base = repairSpans({
    ...cleared,
    rows: cleared.rows.map((row) => (row.id === from.id ? normalizeRow(withoutCell(row, id)) : row)),
  });
  const others = from.slots.reduce((sum, slot) => (slot.id === id ? sum : sum + slot.fr), 0);
  return { base, moving, from: from.id, share: others > 0 ? moving.fr / others : 1 };
}

function gapRows(base: Layout, rowAt: number, left: SlotId | null, right: SlotId | null): [number, number] | null {
  const sides = [left, right].flatMap((cell) => (cell ? [rowsOf(base, cell)] : []));
  if (sides.length === 0 || sides.some((side) => side === null)) return null;
  let first = 0;
  let last = base.rows.length - 1;
  for (const side of sides as [number, number][]) {
    first = Math.max(first, side[0]);
    last = Math.min(last, side[1]);
  }
  return first <= rowAt && rowAt <= last && last > first ? [first, last] : null;
}

function placeColumn(
  base: Layout,
  id: SlotId,
  anchor: SlotId,
  after: boolean,
  first: number,
  last: number,
  own: number | null,
): Layout | null {
  const rows: RowModel[] = [];
  for (let rowAt = 0; rowAt < base.rows.length; rowAt += 1) {
    const row = base.rows[rowAt]!;
    if (rowAt < first || rowAt > last) {
      rows.push(row);
      continue;
    }
    const order = visualOrder(row);
    const found = order.findIndex((entry) => cellOf(entry) === anchor);
    if (found < 0) return null;
    const cut = after ? found + 1 : found;
    const leftOf = order.slice(0, cut).filter((entry) => entry.kind === 'slot').length;
    if (rowAt > first) {
      rows.push({ ...row, reserved: [...(row.reserved ?? []), { of: id, at: leftOf }] });
      continue;
    }
    const held = row.reserved?.map((mark) => {
      const drawnAt = order.findIndex((entry) => entry.kind === 'reserved' && entry.of === mark.of);
      return drawnAt >= cut && mark.at >= leftOf ? { ...mark, at: mark.at + 1 } : mark;
    });
    const count = row.slots.length;
    const slots: Slot[] =
      own === null ? row.slots.map((slot) => ({ ...slot, fr: slot.fr * (count / (count + 1)) })) : row.slots.slice();
    slots.splice(leftOf, 0, { id, fr: own ?? 1 / (count + 1), span: last - first + 1 });
    const placed: RowModel = { ...row, slots, ...(held ? { reserved: held } : {}) };
    rows.push(own === null ? placed : normalizeRow(placed));
  }
  const next = repairSpans({ ...base, rows });
  for (let rowAt = first; rowAt <= last; rowAt += 1) {
    if (!next.rows[rowAt]) return null;
    const order = visualOrder(next.rows[rowAt]!);
    const mine = order.findIndex((entry) => cellOf(entry) === id);
    const theirs = order.findIndex((entry) => cellOf(entry) === anchor);
    if (mine < 0 || theirs < 0 || mine !== (after ? theirs + 1 : theirs - 1)) return null;
  }
  return next;
}

export function landColumnOrRow(layout: Layout, id: SlotId, rowId: RowId, index: number): Layout {
  const row = rowOf(layout, rowId);
  if (!row) return layout;
  const { left, right } = neighboursAt(row, index, id);
  const lifted = lift(layout, id);
  if (!lifted) return layout;
  const rowAt = lifted.base.rows.findIndex((one) => one.id === rowId);
  const span = rowAt < 0 ? null : gapRows(lifted.base, rowAt, left, right);
  if (span) {
    const anchor = left ?? right;
    const own = lifted.base.rows[span[0]]?.id === lifted.from ? lifted.share : null;
    const placed = anchor ? placeColumn(lifted.base, id, anchor, left !== null, span[0], span[1], own) : null;
    if (placed) return placed;
  }
  return moveCell(layout, id, rowId, index);
}
