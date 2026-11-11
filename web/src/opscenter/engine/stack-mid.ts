
import { META } from './meta';
import { freeRowId } from './model';
import { MAX_SPAN, placeOf, spanOf, visualOrder } from './spans';
import { GUTTER, computeTracks } from './tracks';
import type { Layout, Reservation, RowModel, Slot, SlotId } from './types';

const NOMINAL_WIDTH = 1200;
export const NOMINAL_HEIGHT = 800;

function withSpan(slot: Slot, span: number): Slot {
  const { span: _old, ...rest } = slot;
  return span >= 2 ? { ...rest, span } : rest;
}

export function keepRowPx(rows: RowModel[], at: number, height: number): RowModel[] {
  const fixed = rows.reduce((sum, row) => (row.kind === 'px' ? sum + Math.max(1, Math.round(row.size)) : sum), 0);
  const space = Math.floor(height) - fixed - GUTTER * (rows.length - 1);
  const upper = rows[at];
  const lower = rows[at + 1];
  if (space <= GUTTER || !upper || !lower || upper.kind !== 'flex' || lower.kind !== 'flex') return rows;
  const total = rows.reduce((sum, row) => (row.kind === 'flex' ? sum + row.size : sum), 0);
  if (!(total > 0)) return rows;
  const scale = (space + GUTTER) / space / total;
  const pair = upper.size + lower.size;
  return rows.map((row, step) => {
    if (row.kind !== 'flex') return row;
    return { ...row, size: step === at || step === at + 1 ? row.size * scale - (GUTTER / space) * (row.size / pair) : row.size * scale };
  });
}

function splitRow(base: Layout, m: number, top: number, height: number): RowModel[] | null {
  const row = base.rows[m]!;
  const order = visualOrder(row);
  const covering = new Set<SlotId>(order.map((entry) => (entry.kind === 'slot' ? entry.slot.id : entry.of)));
  const rows = base.rows.map((one, at) => ({
    ...one,
    slots: at > m ? one.slots : one.slots.map((slot) => (covering.has(slot.id) && at + spanOf(slot) - 1 >= m ? { ...slot, span: spanOf(slot) + 1 } : slot)),
  }));
  if (rows.some((one) => one.slots.some((slot) => (slot.span ?? 1) > MAX_SPAN))) return null;
  const marks: Reservation[] = order.map((entry) => ({ of: entry.kind === 'slot' ? entry.slot.id : entry.of, at: 0 }));
  const lower: RowModel = { id: freeRowId(base), kind: 'flex', size: row.size - top, slots: [], reserved: marks };
  rows[m] = { ...rows[m]!, size: top };
  rows.splice(m + 1, 0, lower);
  return keepRowPx(rows, m, height);
}

function cutAfter(rows: readonly RowModel[], of: SlotId, id: SlotId, edge: 'above' | 'below', home: number, last: number, k: number, width: number, height: number): RowModel[] | null {
  const out: RowModel[] = rows.map((row) => ({ ...row, slots: row.slots.map((slot) => ({ ...slot })), ...(row.reserved ? { reserved: row.reserved.map((mark) => ({ ...mark })) } : {}) }));
  const homeRow = out[home]!;
  const at = homeRow.slots.findIndex((slot) => slot.id === of);
  const own = homeRow.slots[at];
  const lowerRow = out[k + 1];
  const pin = lowerRow?.reserved?.findIndex((mark) => mark.of === of) ?? -1;
  if (!own || !lowerRow || pin < 0) return null;
  const marks = lowerRow.reserved!;
  const where = marks[pin]!.at;
  const order = visualOrder(lowerRow);
  const mine = order.findIndex((entry) => entry.kind === 'reserved' && entry.of === of);
  const isRight = (mark: Reservation): boolean => order.findIndex((entry) => entry.kind === 'reserved' && entry.of === mark.of) > mine;
  const lo = Math.max(0, ...marks.filter((mark, step) => step !== pin && !isRight(mark)).map((mark) => mark.at));
  const hi = Math.min(lowerRow.slots.length, ...marks.filter((mark, step) => step !== pin && isRight(mark)).map((mark) => mark.at));
  let shares: number[] | null = null;
  if (hi > lo) {
    const cells = computeTracks({ rows, width, height, gutter: GUTTER, metas: META }).rows[k + 1]?.cells ?? [];
    const px = lowerRow.slots.slice(lo, hi).map((slot) => cells.find((cell) => cell.slotId === slot.id)?.width ?? 0);
    const column = cells.find((cell) => cell.reserved && cell.of === of)?.width ?? 0;
    const total = px.reduce((sum, one) => sum + one, column);
    if (!(column > 0) || !(total > 0) || px.some((one) => !(one > 0))) return null;
    shares = [...px.slice(0, where - lo), column, ...px.slice(where - lo)].map((one) => one / total);
  }

  const upperSpan = k - home + 1;
  const lowerSpan = last - k;
  homeRow.slots[at] = edge === 'above' ? withSpan({ id, fr: own.fr }, upperSpan) : withSpan(own, upperSpan);
  if (edge === 'above') {
    for (let at2 = home + 1; at2 <= k; at2 += 1) {
      const row = out[at2]!;
      if (row.reserved) row.reserved = row.reserved.map((mark) => (mark.of === of ? { ...mark, of: id } : mark));
    }
  } else {
    for (let at2 = k + 2; at2 <= last; at2 += 1) {
      const row = out[at2]!;
      if (row.reserved) row.reserved = row.reserved.map((mark) => (mark.of === of ? { ...mark, of: id } : mark));
    }
  }
  lowerRow.reserved = marks.flatMap((mark, step) => (step === pin ? [] : [isRight(mark) ? { ...mark, at: mark.at + 1 } : mark]));
  lowerRow.slots.splice(where, 0, withSpan({ id: edge === 'above' ? of : id, fr: 1 }, lowerSpan));
  if (shares) shares.forEach((share, step) => { lowerRow.slots[lo + step] = { ...lowerRow.slots[lo + step]!, fr: share }; });
  return out;
}

export function cutAtMidpoint(base: Layout, id: SlotId, of: SlotId, edge: 'above' | 'below', width: number = NOMINAL_WIDTH, height: number = NOMINAL_HEIGHT): Layout | 'refused' | null {
  const place = placeOf(base, of);
  const slot = place ? base.rows[place.rowAt]?.slots[place.slotAt] : undefined;
  if (!place || !slot) return null;
  const home = place.rowAt;
  const last = home + Math.min(spanOf(slot), base.rows.length - home) - 1;
  if (last <= home || base.rows.slice(home, last + 1).some((row) => row.kind !== 'flex')) return null;

  const space = Math.max(200, height - GUTTER * base.rows.length);
  const sliver = GUTTER / space;
  const sizes = base.rows.slice(home, last + 1).map((row) => row.size);
  const total = sizes.reduce((sum, size) => sum + size, 0);
  const unlevel = (upper: number, upperRows: number, lowerRows: number): number => Math.abs((2 * upper - total) * space + (upperRows - lowerRows) * GUTTER);
  const cuts: { error: number; row: number; top: number }[] = [];
  let before = 0;
  sizes.forEach((size, step) => {
    const at = home + step;
    if (size >= 2 * sliver) {
      const level = (total / 2 - before) - ((step + 1 - (last - at + 1)) * GUTTER) / (2 * space);
      const top = Math.min(size - sliver, Math.max(sliver, level));
      cuts.push({ error: unlevel(before + top, step + 1, last - at + 1), row: at, top });
    }
    before += size;
    if (at < last) cuts.push({ error: unlevel(before, step + 1, last - at), row: at, top: -1 });
  });
  cuts.sort((a, b) => a.error - b.error);
  for (const cut of cuts) {
    if (cut.top < 0) {
      const snapped = cutAfter(base.rows, of, id, edge, home, last, cut.row, width, height);
      if (snapped) return { ...base, rows: snapped };
      continue;
    }
    const split = splitRow(base, cut.row, cut.top, height);
    if (!split) return 'refused';
    const done = cutAfter(split, of, id, edge, home, last + 1, cut.row, width, height);
    if (done) return { ...base, rows: done };
  }
  return null;
}
