
import { NOMINAL_HEIGHT, NOMINAL_WIDTH } from './fold-size';
import { GUTTER, computeTracks, type CellTrack, type RowTracks } from './tracks';
import { MAX_SPAN, repairSpans, spanOf } from './spans';
import type { Layout, MetaMap, Reservation, RowModel, Slot, SlotId } from './types';


const SNAP = 3;
const SLIVER = 2;

type Problem =
  | { kind: 'gap'; rowAt: number; x: number; end: number }
  | { kind: 'zero'; rowAt: number; index: number };

function ownerOf(cell: CellTrack): SlotId | null {
  return cell.slotId ?? (cell.reserved ? (cell.of ?? null) : null);
}

function slotsLeftOf(row: RowTracks, x: number): number {
  return row.cells.filter((cell) => cell.slotId !== null && cell.x < x - 0.5).length;
}

function pinsOf(row: RowTracks): Map<SlotId, number> {
  return new Map(row.cells.flatMap((cell) => (cell.reserved && cell.of ? [[cell.of, cell.x] as [SlotId, number]] : [])));
}

function mergedPins(held: readonly Reservation[], pins: ReadonlyMap<SlotId, number>, added: readonly { one: Reservation; x: number }[]): Reservation[] {
  const all = [...held.map((one) => ({ one, x: pins.get(one.of) ?? Number.MAX_SAFE_INTEGER })), ...added];
  return all.map((entry, order) => ({ entry, order })).sort((a, b) => a.entry.x - b.entry.x || a.order - b.order).map((item) => item.entry.one);
}

function fractionFor(row: RowModel, track: RowTracks, at: number, width: number): number {
  const cuts = (row.reserved ?? []).map((one) => one.at);
  const start = Math.max(0, ...cuts.filter((cut) => cut <= at));
  const end = Math.min(row.slots.length, ...cuts.filter((cut) => cut > at));
  const others = row.slots.slice(start, end);
  const px = others.reduce((sum, slot) => sum + (track.cells.find((cell) => cell.slotId === slot.id)?.width ?? 0), 0);
  const fr = others.reduce((sum, slot) => sum + slot.fr, 0);
  return px > 0 && fr > 0 ? (width / px) * fr : 1;
}

function firstProblem(layout: Layout, width: number, height: number, metas: MetaMap): Problem | null {
  const tracks = computeTracks({ rows: layout.rows, width, height, gutter: GUTTER, metas });
  for (let rowAt = 0; rowAt < tracks.rows.length; rowAt += 1) {
    const cells = tracks.rows[rowAt]!.cells;
    if (layout.rows[rowAt]!.slots.length === 0) continue;
    const bare = cells.find((cell) => cell.slotId === null && !cell.reserved && cell.width >= SLIVER);
    if (bare) return { kind: 'gap', rowAt, x: bare.x, end: bare.x + bare.width };
    const zero = cells.find((cell) => cell.slotId !== null && cell.width < SLIVER);
    if (zero) return { kind: 'zero', rowAt, index: zero.index };
    const last = cells.reduce((far, cell) => Math.max(far, cell.x + cell.width), 0);
    if (width - last - GUTTER >= SLIVER) return { kind: 'gap', rowAt, x: last + GUTTER, end: width };
  }
  return null;
}

function homeOf(rows: readonly RowModel[], id: SlotId): number {
  return rows.findIndex((row) => row.slots.some((slot) => slot.id === id));
}

function lastRowOf(rows: readonly RowModel[], id: SlotId): number {
  const home = homeOf(rows, id);
  const slot = rows[home]?.slots.find((one) => one.id === id);
  return slot ? home + Math.min(spanOf(slot), rows.length - home) - 1 : -1;
}

function exactCover(row: RowTracks | undefined, x: number, end: number, snap: number = SNAP): CellTrack[] | null {
  const hit = (row?.cells ?? []).filter((cell) => cell.x < end - 1 && cell.x + cell.width > x + 1);
  if (hit.length === 0 || hit.some((cell) => ownerOf(cell) === null)) return null;
  const near = Math.abs(Math.min(...hit.map((cell) => cell.x)) - x) <= snap && Math.abs(Math.max(...hit.map((cell) => cell.x + cell.width)) - end) <= snap;
  return near ? hit : null;
}

function withRow(rows: readonly RowModel[], at: number, row: RowModel): RowModel[] {
  return rows.map((one, index) => (index === at ? row : one));
}

function withReserved(row: RowModel, reserved: readonly Reservation[]): RowModel {
  if (reserved.length > 0) return { ...row, reserved: [...reserved] };
  const { reserved: _gone, ...rest } = row;
  return rest;
}

function extendDown(rows: readonly RowModel[], tracks: readonly RowTracks[], gap: Extract<Problem, { kind: 'gap' }>): RowModel[] | null {
  const above = exactCover(tracks[gap.rowAt - 1], gap.x, gap.end);
  if (!above) return null;
  const owners = [...new Set(above.map((cell) => ownerOf(cell)!))];
  if (owners.some((id) => lastRowOf(rows, id) !== gap.rowAt - 1 || spanOf(rows[homeOf(rows, id)]!.slots.find((slot) => slot.id === id)!) >= MAX_SPAN)) return null;
  const row = rows[gap.rowAt]!;
  const at = slotsLeftOf(tracks[gap.rowAt]!, gap.x);
  const added = owners.map((id) => ({ one: { of: id, at }, x: above.find((cell) => ownerOf(cell) === id)!.x }));
  let out = withRow(rows, gap.rowAt, withReserved(row, mergedPins(row.reserved ?? [], pinsOf(tracks[gap.rowAt]!), added)));
  for (const id of owners) {
    const home = homeOf(out, id);
    out = withRow(out, home, { ...out[home]!, slots: out[home]!.slots.map((slot) => (slot.id === id ? { ...slot, span: spanOf(slot) + 1 } : slot)) });
  }
  return out;
}

function riseInto(rows: readonly RowModel[], tracks: readonly RowTracks[], gap: Extract<Problem, { kind: 'gap' }>): RowModel[] | null {
  const below = exactCover(tracks[gap.rowAt + 1], gap.x, gap.end);
  const cell = below?.length === 1 ? below[0]! : null;
  const lower = rows[gap.rowAt + 1];
  const slot = cell?.slotId ? lower?.slots[cell.index] : undefined;
  if (!cell || !lower || !slot || slot.id !== cell.slotId || spanOf(slot) >= MAX_SPAN) return null;
  const upper = rows[gap.rowAt]!;
  const at = slotsLeftOf(tracks[gap.rowAt]!, gap.x);
  const upperPins = pinsOf(tracks[gap.rowAt]!);
  const slots = [...upper.slots.slice(0, at), { ...slot, fr: fractionFor(upper, tracks[gap.rowAt]!, at, gap.end - gap.x), span: spanOf(slot) + 1 }, ...upper.slots.slice(at)];
  const shifted = (upper.reserved ?? []).map((one) => ((upperPins.get(one.of) ?? -1) > gap.x ? { ...one, at: one.at + 1 } : one));
  const lowerPins = pinsOf(tracks[gap.rowAt + 1]!);
  const kept = (lower.reserved ?? []).map((one) => (one.at > cell.index ? { ...one, at: one.at - 1 } : one));
  const out = withRow(rows, gap.rowAt, withReserved({ ...upper, slots }, shifted));
  return withRow(out, gap.rowAt + 1, withReserved({ ...lower, slots: lower.slots.filter((one) => one.id !== slot.id) }, mergedPins(kept, lowerPins, [{ one: { of: slot.id, at: cell.index }, x: gap.x }])));
}

function riseBesideSpanner(rows: readonly RowModel[], tracks: readonly RowTracks[], zero: Extract<Problem, { kind: 'zero' }>): RowModel[] | null {
  const cells = tracks[zero.rowAt]!.cells;
  const me = cells.findIndex((cell) => cell.slotId !== null && cell.index === zero.index);
  const previous = cells[me - 1];
  const next = cells[me + 1];
  const after = !!previous?.reserved && !!previous.of;
  const pin = after ? previous : next?.reserved && next.of ? next : undefined;
  const slot = rows[zero.rowAt]?.slots[zero.index];
  const owner = pin?.of;
  const home = owner ? homeOf(rows, owner) : -1;
  if (!pin || !owner || !slot || home < 0 || home >= zero.rowAt || zero.rowAt - home + spanOf(slot) > MAX_SPAN) return null;
  const box = tracks[home]!.cells.find((cell) => cell.slotId === owner);
  if (!box) return null;
  const homeRow = rows[home]!;
  const insertAt = homeRow.slots.findIndex((one) => one.id === owner) + (after ? 1 : 0);
  const homePins = pinsOf(tracks[home]!);
  const peer = homeRow.slots.find((one) => one.id === owner)!;
  const rising: Slot = { ...slot, fr: peer.fr, span: zero.rowAt - home + spanOf(slot) };
  const homeSlots = [...homeRow.slots.slice(0, insertAt), rising, ...homeRow.slots.slice(insertAt)];
  const homeHeld = (homeRow.reserved ?? []).map((one) => ((homePins.get(one.of) ?? -1) > box.x ? { ...one, at: one.at + 1 } : one));
  let out = withRow(rows, home, withReserved({ ...homeRow, slots: homeSlots }, homeHeld));
  const key = box.x + (after ? 0.5 : -0.5);
  for (let rowAt = home + 1; rowAt <= zero.rowAt; rowAt += 1) {
    const row = out[rowAt]!;
    const at = rowAt === zero.rowAt ? zero.index : slotsLeftOf(tracks[rowAt]!, box.x);
    const base = rowAt === zero.rowAt ? row.slots.filter((one) => one.id !== slot.id) : row.slots;
    const held = (row.reserved ?? []).map((one) => (rowAt === zero.rowAt && one.at > zero.index ? { ...one, at: one.at - 1 } : one));
    out = withRow(out, rowAt, withReserved({ ...row, slots: base }, mergedPins(held, pinsOf(tracks[rowAt]!), [{ one: { of: slot.id, at }, x: key }])));
  }
  return out;
}

export function fillLiftedGaps(layout: Layout, width: number, height: number, metas: MetaMap): Layout {
  let now = layout;
  for (let pass = 0; pass < layout.rows.length * 3; pass += 1) {
    const problem = firstProblem(now, width, height, metas);
    if (!problem) return now;
    const tracks = computeTracks({ rows: now.rows, width, height, gutter: GUTTER, metas }).rows;
    const rows =
      problem.kind === 'zero'
        ? riseBesideSpanner(now.rows, tracks, problem)
        : ((problem.rowAt > 0 ? extendDown(now.rows, tracks, problem) : null) ?? riseInto(now.rows, tracks, problem));
    if (!rows) return layout;
    now = repairSpans({ ...now, rows });
  }
  return firstProblem(now, width, height, metas) ? layout : now;
}

export function giveFreedWidth(row: RowModel, id: SlotId, span: number = 1, track?: RowTracks): RowModel | null {
  const at = row.slots.findIndex((slot) => slot.id === id);
  if (at < 0) return row;
  const cuts = (row.reserved ?? []).map((one) => one.at);
  const start = Math.max(0, ...cuts.filter((cut) => cut <= at));
  const end = Math.min(row.slots.length, ...cuts.filter((cut) => cut > at));
  if (!row.slots.some((slot, index) => index >= start && index < end && index !== at && spanOf(slot) > 1)) return row;
  const inPocket = (index: number): boolean => index >= start && index < end;
  const twin = (index: number): boolean => inPocket(index) && span > 1 && spanOf(row.slots[index]!) === span;
  const plain = (index: number): boolean => inPocket(index) && spanOf(row.slots[index]!) <= Math.max(1, span);
  const heir = [twin(at - 1) ? at - 1 : -1, twin(at + 1) ? at + 1 : -1, plain(at - 1) ? at - 1 : -1, plain(at + 1) ? at + 1 : -1].find((one) => one >= 0) ?? -1;
  if (heir < 0) return null;
  const px = row.slots.map((slot) => track?.cells.find((cell) => cell.slotId === slot.id)?.width ?? 0);
  const space = px.slice(start, end).reduce((sum, one) => sum + one, 0) + GUTTER;
  if (track && px.slice(start, end).every((one) => one > 0)) {
    return { ...row, slots: row.slots.map((slot, index) => (index < start || index >= end ? slot : { ...slot, fr: (px[index]! + (index === heir ? px[at]! + GUTTER : 0)) / space })) };
  }
  const gift = row.slots[at]!.fr;
  return { ...row, slots: row.slots.map((slot, index) => (index === heir ? { ...slot, fr: slot.fr + gift } : slot)) };
}

function bareBetween(row: RowTracks | undefined, x: number, end: number, leaver: SlotId): boolean {
  const hit = (row?.cells ?? []).filter((cell) => cell.x < end - 1 && cell.x + cell.width > x + 1);
  return hit.length > 0 && hit.every((cell) => ownerOf(cell) === null || ownerOf(cell) === leaver) && Math.abs(Math.min(...hit.map((cell) => cell.x)) - x) <= 1.5 && Math.abs(Math.max(...hit.map((cell) => cell.x + cell.width)) - end) <= 1.5;
}

function keepPocketPixels(row: RowModel, at: number, track: RowTracks, widths: readonly number[]): Slot[] | null {
  const cuts = (row.reserved ?? []).map((one) => one.at);
  const start = Math.max(0, ...cuts.filter((cut) => cut <= at));
  const end = Math.min(row.slots.length, ...cuts.filter((cut) => cut > at));
  const px = row.slots.map((slot) => track.cells.find((cell) => cell.slotId === slot.id)?.width ?? 0);
  if (px.slice(start, end).some((one) => !(one > 0))) return null;
  const space = px.slice(start, end).reduce((sum, one) => sum + one, 0) - (widths.length - 1) * GUTTER;
  if (!(space > 0)) return null;
  const spots = row.slots.map((slot, index) => (index >= start && index < end && index !== at ? { ...slot, fr: px[index]! / space } : slot));
  const into = widths.map((one) => ({ ...row.slots[at]!, fr: one / space }));
  return [...spots.slice(0, at), ...into, ...spots.slice(at + 1)];
}

export function riseIntoLeaver(rows: readonly RowModel[], id: SlotId, metas: MetaMap, width: number = NOMINAL_WIDTH, height: number = NOMINAL_HEIGHT): RowModel[] | null {
  const rowAt = homeOf(rows, id);
  const upper = rows[rowAt];
  const leaver = upper?.slots.find((slot) => slot.id === id);
  if (!upper || !leaver) return null;
  const tracks = computeTracks({ rows, width, height, gutter: GUTTER, metas }).rows;
  const mine = tracks[rowAt]!.cells.find((cell) => cell.slotId === id);
  if (!mine) return null;
  const end = mine.x + mine.width;
  let down = rowAt + 1;
  while (down < rows.length && bareBetween(tracks[down], mine.x, end, id)) down += 1;
  const lower = rows[down];
  const below = lower ? exactCover(tracks[down], mine.x, end, 1.5) : null;
  const cells = below?.filter((cell) => cell.slotId !== null) ?? [];
  const risers = cells.map((cell) => lower?.slots[cell.index]);
  if (!lower || !below || cells.length !== below.length || risers.some((slot, at) => !slot || slot.id !== cells[at]!.slotId || spanOf(slot) >= MAX_SPAN || down - rowAt + spanOf(slot) > MAX_SPAN)) return null;
  const wide = cells.reduce((sum, cell) => sum + cell.width, 0);
  const rising = risers.map((slot, at) => ({ ...slot!, fr: (leaver.fr * cells[at]!.width) / wide, span: down - rowAt + spanOf(slot!) }));
  const at = upper.slots.findIndex((one) => one.id === id);
  const pocket = keepPocketPixels(upper, at, tracks[rowAt]!, cells.map((cell) => cell.width));
  const slotsOut = pocket ? [...pocket.slice(0, at), ...rising.map((slot, step) => ({ ...slot, fr: pocket[at + step]!.fr })), ...pocket.slice(at + rising.length)] : [...upper.slots.slice(0, at), ...rising, ...upper.slots.slice(at + 1)];
  const upperHeld = (upper.reserved ?? []).map((one) => (one.at > at ? { ...one, at: one.at + rising.length - 1 } : one));
  let out = withRow(rows, rowAt, withReserved({ ...upper, slots: slotsOut }, upperHeld));
  for (let step = rowAt + 1; step < down; step += 1) {
    const row = out[step]!;
    const added = rising.map((slot, index) => ({ one: { of: slot.id, at: slotsLeftOf(tracks[step]!, cells[index]!.x) }, x: cells[index]!.x }));
    out = withRow(out, step, withReserved(row, mergedPins((row.reserved ?? []).filter((one) => one.of !== id), pinsOf(tracks[step]!), added)));
  }
  const first = cells[0]!.index;
  const gone = new Set(rising.map((slot) => slot.id));
  const kept = (lower.reserved ?? []).map((one) => (one.at > first ? { ...one, at: one.at - rising.length } : one));
  const added = rising.map((slot, index) => ({ one: { of: slot.id, at: first }, x: cells[index]!.x }));
  return withRow(out, down, withReserved({ ...lower, slots: lower.slots.filter((one) => !gone.has(one.id)) }, mergedPins(kept, pinsOf(tracks[down]!), added)));
}

export function keepCoveredWidths(rows: readonly RowModel[], before: readonly RowModel[], id: SlotId, metas: MetaMap, width: number = NOMINAL_WIDTH, height: number = NOMINAL_HEIGHT): RowModel[] {
  const home = homeOf(before, id);
  const covered = new Set(before.filter((row, at) => at !== home && row.reserved?.some((one) => one.of === id)).map((row) => row.id));
  if (covered.size === 0) return [...rows];
  const tracks = computeTracks({ rows: before, width, height, gutter: GUTTER, metas }).rows;
  const drawn = new Map(tracks.flatMap((row) => row.cells.flatMap((cell) => (cell.slotId ? [[cell.slotId, cell.width] as [SlotId, number]] : []))));
  return rows.map((row) => {
    if (!covered.has(row.id) || row.slots.some((slot) => !((drawn.get(slot.id) ?? 0) > 0))) return row;
    return { ...row, slots: row.slots.map((slot) => ({ ...slot, fr: drawn.get(slot.id)! })) };
  });
}
