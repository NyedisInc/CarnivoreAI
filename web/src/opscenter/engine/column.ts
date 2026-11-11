
import { foldLifted } from './compact';
import { COL_MIN } from './floors';
import { META } from './meta';
import { liftedRows, moveCell, normalizeRow, rowOf, rowOfCell } from './model';
import { clearSpan, placeOf, repairSpans, spanOf, visualOrder, type VisualCell } from './spans';
import { computeTracks, GUTTER, type RowTracks } from './tracks';
import type { Layout, MetaMap, RowId, RowModel, Slot, SlotId } from './types';

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

function lift(layout: Layout, id: SlotId, width: number = NOMINAL_WIDTH, height: number = NOMINAL_HEIGHT): { base: Layout; moving: Slot; from: RowId; share: number } | null {
  const cleared = clearSpan(layout, id);
  const from = rowOfCell(cleared, id);
  const moving = from?.slots.find((slot) => slot.id === id);
  if (!from || !moving) return null;
  const base = repairSpans({
    ...cleared,
    rows: liftedRows(layout, id, width, true, height),
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

interface Cut {
  rowAt: number;
  cut: number;
}

type Shape = (at: { slots: Slot[]; leftOf: number; order: VisualCell[]; cut: number; rowAt: number }) => Slot[] | null;

function placeAtCuts(
  base: Layout,
  id: SlotId,
  cuts: readonly Cut[],
  shape: Shape,
  normalize: boolean,
  beside: SlotId | null,
  after: boolean,
): Layout | null {
  const first = cuts[0]?.rowAt ?? -1;
  const cutAt = new Map(cuts.map((one) => [one.rowAt, one.cut]));
  const rows: RowModel[] = [];
  for (let rowAt = 0; rowAt < base.rows.length; rowAt += 1) {
    const row = base.rows[rowAt]!;
    const cut = cutAt.get(rowAt);
    if (cut === undefined) {
      rows.push(row);
      continue;
    }
    const order = visualOrder(row);
    const leftOf = order.slice(0, cut).filter((entry) => entry.kind === 'slot').length;
    if (rowAt > first) {
      rows.push({ ...row, reserved: [...(row.reserved ?? []), { of: id, at: leftOf }] });
      continue;
    }
    const held = row.reserved?.map((mark) => {
      const drawnAt = order.findIndex((entry) => entry.kind === 'reserved' && entry.of === mark.of);
      return drawnAt >= cut && mark.at >= leftOf ? { ...mark, at: mark.at + 1 } : mark;
    });
    const slots = shape({ slots: row.slots.slice(), leftOf, order, cut, rowAt });
    if (!slots) return null;
    const placed: RowModel = { ...row, slots, ...(held ? { reserved: held } : {}) };
    rows.push(normalize ? normalizeRow(placed) : placed);
  }
  const next = repairSpans({ ...base, rows });
  for (let rowAt = first; rowAt < first + cuts.length; rowAt += 1) {
    if (!next.rows[rowAt]) return null;
    const order = visualOrder(next.rows[rowAt]!);
    const mine = order.findIndex((entry) => cellOf(entry) === id);
    if (mine < 0) return null;
    const theirs = beside === null ? 0 : order.findIndex((entry) => cellOf(entry) === beside);
    if (theirs < 0 || (beside !== null && mine !== theirs + (after ? 1 : -1))) return null;
  }
  return next;
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
  const cuts: Cut[] = [];
  for (let rowAt = first; rowAt <= last; rowAt += 1) {
    const found = visualOrder(base.rows[rowAt]!).findIndex((entry) => cellOf(entry) === anchor);
    if (found < 0) return null;
    cuts.push({ rowAt, cut: after ? found + 1 : found });
  }
  const shape: Shape = ({ slots, leftOf }) => {
    const count = slots.length;
    const out: Slot[] = own === null ? slots.map((slot) => ({ ...slot, fr: slot.fr * (count / (count + 1)) })) : slots;
    out.splice(leftOf, 0, { id, fr: own ?? 1 / (count + 1), span: last - first + 1 });
    return out;
  };
  return placeAtCuts(base, id, cuts, shape, own !== null, anchor, after);
}

const NOMINAL_WIDTH = 1200;
const NOMINAL_HEIGHT = 800;

function pocketRun(order: readonly VisualCell[], from: number): Slot[] {
  if (order[from]?.kind !== 'slot') return [];
  let start = from;
  let end = from;
  while (start > 0 && order[start - 1]?.kind === 'slot') start -= 1;
  while (end + 1 < order.length && order[end + 1]?.kind === 'slot') end += 1;
  return order.slice(start, end + 1).flatMap((entry) => (entry.kind === 'slot' ? [entry.slot] : []));
}

function pocketSpace(drawn: RowTracks | undefined, run: readonly Slot[]): number {
  const px = run.reduce((sum, slot) => sum + (drawn?.cells.find((cell) => cell.slotId === slot.id)?.width ?? 0), 0);
  return px + GUTTER * Math.max(0, run.length - 1);
}

export function landSplit(
  layout: Layout,
  id: SlotId,
  of: SlotId,
  side: 'left' | 'right',
  width: number = NOMINAL_WIDTH,
  metas: MetaMap = META,
  height: number = NOMINAL_HEIGHT,
): Layout {
  const lifted = id === of ? null : lift(layout, id, width, height);
  const base = lifted ? foldLifted(layout, lifted.base, id, metas, width, height) : null;
  const span = base ? rowsOf(base, of) : null;
  if (!base || !span) return layout;
  const [first, last] = span;
  const target = base.rows[first]!.slots.find((slot) => slot.id === of);
  if (!target) return layout;
  const cuts: Cut[] = [];
  for (let rowAt = first; rowAt <= last; rowAt += 1) {
    const found = visualOrder(base.rows[rowAt]!).findIndex((entry) => cellOf(entry) === of);
    if (found < 0) return layout;
    cuts.push({ rowAt, cut: side === 'right' ? found + 1 : found });
  }
  const tracks = computeTracks({ rows: base.rows, width, height, gutter: GUTTER, metas });
  const shape: Shape = ({ slots, leftOf, order, rowAt }) => {
    const run = pocketRun(order, order.findIndex((entry) => cellOf(entry) === of));
    const space = pocketSpace(tracks.rows[rowAt], run);
    const pair = target.fr - (run.reduce((sum, slot) => sum + slot.fr, 0) * GUTTER) / space;
    if (!(space > 0) || !(pair > 0)) return null;
    const out = slots.map((slot) => (slot.id === of ? { ...slot, fr: pair / 2 } : slot));
    out.splice(leftOf, 0, { id, fr: pair / 2, span: cuts.length });
    return out;
  };
  return placeAtCuts(base, id, cuts, shape, true, of, side === 'right') ?? layout;
}

export interface SeamRow {
  row: RowId;
  left: SlotId | null;
  right: SlotId | null;
}

function seamCut(order: readonly VisualCell[], seam: SeamRow, dragged: SlotId): number | null {
  const at = (cell: SlotId): number => order.findIndex((entry) => cellOf(entry) === cell);
  const left = seam.left !== null && seam.left !== dragged ? seam.left : null;
  const right = seam.right !== null && seam.right !== dragged ? seam.right : null;
  if (left !== null) {
    const found = at(left);
    if (found < 0 || (right !== null && cellOf(order[found + 1]) !== right)) return null;
    return found + 1;
  }
  if (right !== null) {
    const found = at(right);
    return found < 0 ? null : found;
  }
  if (seam.left === null && seam.right === dragged) return 0;
  if (seam.right === null && seam.left === dragged) return order.length;
  return null;
}

export function landSeam(layout: Layout, id: SlotId, seam: readonly SeamRow[], width: number = NOMINAL_WIDTH, metas: MetaMap = META, height: number = NOMINAL_HEIGHT): Layout {
  const lifted = lift(layout, id, width, height);
  if (!lifted) return layout;
  const { base } = lifted;
  const found: Cut[] = [];
  for (const one of seam) {
    const rowAt = base.rows.findIndex((row) => row.id === one.row);
    const cut = rowAt < 0 ? null : seamCut(visualOrder(base.rows[rowAt]!), one, id);
    if (cut !== null) found.push({ rowAt, cut });
  }
  found.sort((a, b) => a.rowAt - b.rowAt);
  const cuts = found.filter((one, at) => one.rowAt === (found[0]?.rowAt ?? 0) + at);
  if (cuts.length === 0) return layout;
  const k = Math.max(...cuts.map((one) => visualOrder(base.rows[one.rowAt]!).length));
  const tracks = computeTracks({ rows: base.rows, width, height, gutter: GUTTER, metas });
  const shape: Shape = ({ slots, leftOf, order, cut, rowAt }) => {
    const run = pocketRun(order, order[cut - 1]?.kind === 'slot' ? cut - 1 : cut);
    let fr = 1;
    if (run.length > 0) {
      const room = pocketSpace(tracks.rows[rowAt], run) - GUTTER;
      const own = Math.min((width - k * GUTTER) / (k + 1), room - run.length * COL_MIN);
      if (!(own > 0) || !(room > own)) return null;
      fr = (run.reduce((sum, slot) => sum + slot.fr, 0) * own) / (room - own);
    }
    const out = slots.slice();
    out.splice(leftOf, 0, { id, fr, span: cuts.length });
    return out;
  };
  return placeAtCuts(base, id, cuts, shape, true, null, false) ?? layout;
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
