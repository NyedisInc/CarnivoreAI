
import { COL_MIN } from './floors';
import { NOMINAL_HEIGHT as CHECK_HEIGHT, NOMINAL_WIDTH as CHECK_WIDTH, flexTotal, mergedFlexSize, restoreFlexTotal } from './fold-size';
import { fillLiftedGaps } from './lift-fill';
import { META } from './meta';
import { GUTTER, computeTracks } from './tracks';
import { repairSpans, spanOf, visualOrder } from './spans';
import type { Layout, MetaMap, Reservation, RowId, RowModel, Slot, SlotId } from './types';

export interface Compacted {
  layout: Layout;
  covers: Map<RowId, RowId[]>;
}

function lastRows(rows: readonly RowModel[]): Map<SlotId, number> {
  const out = new Map<SlotId, number>();
  rows.forEach((row, at) => {
    for (const slot of row.slots) out.set(slot.id, at + Math.min(spanOf(slot), rows.length - at) - 1);
  });
  return out;
}

function foldable(rows: readonly RowModel[], at: number, last: ReadonlyMap<SlotId, number>): boolean {
  const upper = rows[at];
  const lower = rows[at + 1];
  if (!upper || !lower || lower.slots.length === 0) return false;
  return visualOrder(upper).every((entry) => {
    const cell = entry.kind === 'slot' ? entry.slot.id : entry.of;
    return (last.get(cell) ?? -1) > at;
  });
}

function keptFractions(wide: readonly (number | undefined)[], reserved: readonly Reservation[]): number[] {
  const cuts = new Set(reserved.map((one) => one.at));
  const out: number[] = [];
  let from = 0;
  for (let at = 1; at <= wide.length; at += 1) {
    if (at < wide.length && !cuts.has(at)) continue;
    const group = wide.slice(from, at);
    const known = group.filter((one): one is number => one !== undefined);
    const mean = known.length ? known.reduce((sum, one) => sum + one, 0) / known.length : 0;
    const filled = group.map((one) => one ?? mean);
    const total = filled.reduce((sum, one) => sum + one, 0);
    const usable = known.length > 0 && known.every((one) => one >= COL_MIN);
    for (const one of filled) out.push(usable ? one / total : 1 / group.length);
    from = at;
  }
  return out;
}


function fold(rows: readonly RowModel[], at: number, was?: ReadonlyMap<SlotId, number>, height: number = CHECK_HEIGHT): RowModel[] {
  const upper = rows[at]!;
  const lower = rows[at + 1]!;
  const homed = new Map<SlotId, Slot>(upper.slots.map((slot) => [slot.id, slot]));
  const slots: Slot[] = [];
  const reserved: Reservation[] = [];
  for (const entry of visualOrder(lower)) {
    if (entry.kind === 'slot') {
      slots.push(entry.slot);
      continue;
    }
    const own = homed.get(entry.of);
    if (!own) {
      reserved.push({ of: entry.of, at: slots.length });
      continue;
    }
    const span = spanOf(own) - 1;
    const { span: _old, ...rest } = own;
    slots.push(span >= 2 ? { ...rest, span } : rest);
  }
  const share = keptFractions(slots.map((slot) => was?.get(slot.id)), reserved);
  const even = slots.map((slot, step) => ({ ...slot, fr: share[step] ?? 1 / slots.length }));
  const size = upper.kind === 'flex' ? mergedFlexSize(rows, [upper, lower], upper.size + lower.size, 1, height) : upper.size + lower.size + GUTTER;
  const merged: RowModel = { id: upper.id, kind: upper.kind, size, slots: even, ...(reserved.length ? { reserved } : {}) };

  const passing = new Set((upper.reserved ?? []).map((one) => one.of));
  const out: RowModel[] = rows.slice(0, at).map((row) =>
    row.slots.some((slot) => passing.has(slot.id))
      ? { ...row, slots: row.slots.map((slot) => (passing.has(slot.id) ? { ...slot, span: spanOf(slot) - 1 } : slot)) }
      : row,
  );
  out.push(merged, ...rows.slice(at + 2));
  return restoreFlexTotal(out, flexTotal(rows));
}

export function foldSpanOnlyRows(layout: Layout, keepPixels: boolean = false, height: number = CHECK_HEIGHT): Layout {
  let rows: RowModel[] = layout.rows.map((row) => ({ ...row, slots: row.slots.map((slot) => ({ ...slot })) }));
  let changed = false;
  const total = flexTotal(rows);
  for (let at = rows.length - 1; at >= 1; at -= 1) {
    if (rows[at]!.slots.length > 0) continue;
    const up = rows[at - 1]!;
    const gone = rows[at]!;
    rows[at - 1] = { ...up, size: up.kind !== 'flex' ? up.size + gone.size + GUTTER : keepPixels ? mergedFlexSize(rows, [up, gone], up.size + gone.size, 1, height) : up.size + gone.size };
    rows.forEach((row, home) => {
      if (home >= at) return;
      row.slots = row.slots.map((slot) => {
        if (home + spanOf(slot) - 1 < at) return slot;
        const { span: _old, ...rest } = slot;
        const span = spanOf(slot) - 1;
        return span >= 2 ? { ...rest, span } : rest;
      });
    });
    rows = rows.filter((_row, index) => index !== at);
    changed = true;
  }
  return changed ? repairSpans({ ...layout, rows: keepPixels ? restoreFlexTotal(rows, total) : rows }) : layout;
}

export function compactRows(layout: Layout, was?: ReadonlyMap<SlotId, number>, height: number = CHECK_HEIGHT): Compacted {
  const covers = new Map<RowId, RowId[]>(layout.rows.map((row) => [row.id, [row.id]]));
  let rows: readonly RowModel[] = layout.rows;
  let changed = false;
  const spanFolded = foldSpanOnlyRows(layout, true, height);
  if (spanFolded !== layout) {
    const keep = new Set(spanFolded.rows.map((row) => row.id));
    let owner = layout.rows[0]!.id;
    for (const row of layout.rows) {
      if (keep.has(row.id)) owner = row.id;
      else {
        covers.set(owner, [...(covers.get(owner) ?? [owner]), row.id]);
        covers.delete(row.id);
      }
    }
    rows = spanFolded.rows;
    changed = true;
  }
  for (let guard = 0; guard < layout.rows.length; guard += 1) {
    const last = lastRows(rows);
    const at = rows.findIndex((_row, index) => foldable(rows, index, last));
    if (at < 0) break;
    const upper = rows[at]!.id;
    const lower = rows[at + 1]!.id;
    covers.set(upper, [...(covers.get(upper) ?? [upper]), ...(covers.get(lower) ?? [lower])]);
    covers.delete(lower);
    rows = repairSpans({ ...layout, rows: fold(rows, at, was, height) }).rows;
    changed = true;
  }
  return { layout: changed ? { ...layout, rows: rows as RowModel[] } : layout, covers };
}

function drawn(layout: Layout, metas: MetaMap): Set<SlotId> {
  const tracks = computeTracks({ rows: layout.rows, width: CHECK_WIDTH, height: CHECK_HEIGHT, gutter: GUTTER, metas });
  const out = new Set<SlotId>();
  for (const row of tracks.rows) {
    for (const cell of row.cells) {
      if (cell.slotId && cell.width > 0 && cell.x + cell.width <= CHECK_WIDTH) out.add(cell.slotId);
    }
  }
  return out;
}

function widthsOf(layout: Layout, metas: MetaMap, skip: SlotId, width: number = CHECK_WIDTH, height: number = CHECK_HEIGHT): Map<SlotId, number> {
  const tracks = computeTracks({ rows: layout.rows, width, height, gutter: GUTTER, metas });
  const out = new Map<SlotId, number>();
  for (const row of tracks.rows) for (const cell of row.cells) if (cell.slotId && cell.slotId !== skip) out.set(cell.slotId, cell.width);
  return out;
}

function placedIds(layout: Layout): string {
  return layout.rows
    .flatMap((row) => row.slots.map((slot) => slot.id))
    .sort()
    .join('\n');
}

export function foldLifted(before: Layout, lifted: Layout, id: SlotId, metas: MetaMap = META, width: number = CHECK_WIDTH, height: number = CHECK_HEIGHT): Layout {
  return fillLiftedGaps(compactRows(lifted, widthsOf(before, metas, id, width, height), height).layout, width, height, metas);
}

export function settleDrop(before: Layout, raw: Layout, id: SlotId, metas: MetaMap = META): Compacted | null {
  const settled = compactRows(raw, widthsOf(before, metas, id));
  const after = settled.layout;
  if (placedIds(after) !== placedIds(before)) return null;
  if (after.hidden.join('\n') !== before.hidden.join('\n')) return null;
  const was = drawn(before, metas);
  const now = drawn(after, metas);
  for (const cell of was) if (!now.has(cell)) return null;
  if (!now.has(id)) return null;
  return settled;
}
