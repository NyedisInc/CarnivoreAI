
import { COL_MIN } from './floors';
import { spanOf, visualOrder } from './spans';
import type { MetaMap, RowId, RowKind, RowModel, SlotId } from './types';

export interface CellTrack {
  slotId: SlotId | null;
  index: number;
  x: number;
  width: number;
  span: number;
  reserved: boolean;
}

export interface SeamTrack {
  afterVisual: number;
  index: number;
  x: number;
  leftMinPx: number;
  leftMaxPx: number;
  leftPx: number;
  pairPx: number;
  space: number;
}

export interface RowTracks {
  id: RowId;
  kind: RowKind;
  top: number;
  height: number;
  template: string;
  free: number;
  cells: CellTrack[];
  seams: SeamTrack[];
}

export interface SurfaceTracks {
  rows: RowTracks[];
  template: string;
  contentHeight: number;
  flexSpace: number;
  spanHeight: Map<SlotId, number>;
}

export const GUTTER = 12;

/* and stopping at */
export const CELL_SQUEEZE_MIN = 44;

interface SpanBox {
  x: number;
  width: number;
}

export interface TrackInput {
  rows: readonly RowModel[];
  width: number;
  height: number;
  gutter: number;
  metas?: MetaMap;
}

export function sharePixels(fractions: readonly number[], total: number): number[] {
  if (!fractions.length || total <= 0) return fractions.map(() => 0);
  const sum = fractions.reduce((carry, one) => carry + (Number.isFinite(one) && one > 0 ? one : 0), 0);
  const scale = sum > 0 ? 1 / sum : 1 / fractions.length;
  const exact = fractions.map((one) => (Number.isFinite(one) && one > 0 ? one : 0) * scale * total);
  const whole = exact.map(Math.floor);
  let left = Math.round(total) - whole.reduce((carry, one) => carry + one, 0);
  const order = exact
    .map((value, index) => ({ index, rest: value - Math.floor(value) }))
    .sort((a, b) => b.rest - a.rest);
  for (const entry of order) {
    if (left <= 0) break;
    whole[entry.index] = (whole[entry.index] ?? 0) + 1;
    left -= 1;
  }
  return whole;
}

export function columnSpace(widthPx: number, columns: number, gutter: number): number {
  return Math.max(1, Math.floor(widthPx) - gutter * Math.max(0, columns - 1));
}

function giveRoom(cells: readonly CellTrack[], from: number, step: 1 | -1): number {
  let room = 0;
  for (let at = from; at >= 0 && at < cells.length; at += step) {
    const cell = cells[at];
    if (!cell || cell.slotId === null) break;
    room += Math.max(0, cell.width - COL_MIN);
  }
  return room;
}

export function squeezeFloor(row: RowModel): number {
  return row.slots.length * COL_MIN;
}

function spanCeiling(
  rows: readonly RowModel[],
  rowAt: number,
  self: SlotId,
  partner: SlotId | null,
  reach: number,
  widthPx: number,
  gutter: number,
  boxes: ReadonlyMap<SlotId, SpanBox>,
): number {
  let ceiling = Number.POSITIVE_INFINITY;
  for (let step = 1; step < reach; step += 1) {
    const under = rows[rowAt + step];
    if (!under) continue;
    const columns = visualOrder(under).length;
    const others = (under.reserved ?? []).reduce(
      (carry, one) => (one.of === self || one.of === partner ? carry : carry + (boxes.get(one.of)?.width ?? 0)),
      0,
    );
    ceiling = Math.min(ceiling, columnSpace(widthPx, columns, gutter) - squeezeFloor(under) - others);
  }
  return ceiling;
}

export function computeTracks(input: TrackInput): SurfaceTracks {
  const { rows, gutter } = input;
  const width = Math.max(0, Math.floor(input.width));
  const bands = gutter * Math.max(0, rows.length - 1);

  const fixed = rows.reduce((carry, row) => (row.kind === 'px' ? carry + Math.max(1, Math.round(row.size)) : carry), 0);
  const flexRows = rows.filter((row) => row.kind === 'flex');
  const flexSpace = flexRows.length > 0 ? Math.max(0, Math.floor(input.height) - fixed - bands) : 0;
  const flexPx = sharePixels(flexRows.map((row) => row.size), flexSpace);
  const heights: number[] = [];
  let flexAt = 0;
  for (const row of rows) {
    if (row.kind === 'px') heights.push(Math.max(1, Math.round(row.size)));
    else {
      heights.push(Math.max(1, flexPx[flexAt] ?? 0));
      flexAt += 1;
    }
  }

  const spanBox = new Map<SlotId, SpanBox>();
  const spanHeight = new Map<SlotId, number>();
  const out: RowTracks[] = [];
  let top = 0;

  for (let rowAt = 0; rowAt < rows.length; rowAt += 1) {
    const row = rows[rowAt];
    const height = heights[rowAt] ?? 0;
    if (!row) continue;
    const order = visualOrder(row);

    const pinned = order.map((cell) => (cell.kind === 'reserved' ? (spanBox.get(cell.of) ?? { x: 0, width: 0 }) : null));

    const cells: CellTrack[] = [];
    const tracks: string[] = [];
    let cursor = 0;
    let free = 0;
    let at = 0;
    while (at < order.length) {
      const pin = pinned[at];
      if (pin) {
        const hole = Math.round(pin.x) - cursor - gutter;
        if (hole >= 1) {
          cells.push({ slotId: null, index: -1, x: cursor, width: hole, span: 1, reserved: false });
          tracks.push(`${hole}px`);
          cursor += hole + gutter;
        }
        const px = Math.max(0, Math.min(Math.round(pin.width), width - cursor));
        cells.push({ slotId: null, index: -1, x: cursor, width: px, span: 1, reserved: true });
        tracks.push(`${px}px`);
        cursor += px + gutter;
        at += 1;
        continue;
      }
      let end = at;
      while (end < order.length && !pinned[end]) end += 1;
      const pocket = order.slice(at, end).flatMap((cell) => (cell.kind === 'slot' ? [cell] : []));
      const next = pinned[end];
      const edge = next ? Math.max(cursor, Math.round(next.x) - gutter) : width;
      const space = Math.max(0, edge - cursor - gutter * (pocket.length - 1));
      const widths = sharePixels(pocket.map((one) => one.slot.fr), space);
      free += space;
      for (let step = 0; step < pocket.length; step += 1) {
        const one = pocket[step];
        if (!one) continue;
        const px = widths[step] ?? 0;
        const reach = Math.min(spanOf(one.slot), rows.length - rowAt);
        cells.push({ slotId: one.slot.id, index: one.index, x: cursor, width: px, span: reach, reserved: false });
        tracks.push(`${px}px`);
        if (reach >= 2) {
          spanBox.set(one.slot.id, { x: cursor, width: px });
          let tall = 0;
          for (let more = 0; more < reach; more += 1) tall += heights[rowAt + more] ?? 0;
          spanHeight.set(one.slot.id, tall + gutter * (reach - 1));
        }
        cursor += px + gutter;
      }
      at = end;
    }

    const seams: SeamTrack[] = [];
    for (let seamAt = 0; seamAt < cells.length - 1; seamAt += 1) {
      const left = cells[seamAt];
      const right = cells[seamAt + 1];
      if (!left || !right || left.slotId === null || right.slotId === null) continue;
      const pair = left.width + right.width;
      const pairFr = (row.slots[left.index]?.fr ?? 0) + (row.slots[right.index]?.fr ?? 0);
      let low = left.width - giveRoom(cells, seamAt, -1);
      let high = left.width + giveRoom(cells, seamAt + 1, 1);
      if (left.span >= 2) {
        high = Math.min(high, spanCeiling(rows, rowAt, left.slotId, right.slotId, left.span, width, gutter, spanBox));
      }
      if (right.span >= 2) {
        low = Math.max(low, pair - spanCeiling(rows, rowAt, right.slotId, left.slotId, right.span, width, gutter, spanBox));
      }
      if (high < left.width) high = left.width;
      if (low > left.width) low = left.width;
      seams.push({
        afterVisual: seamAt,
        index: left.index,
        x: left.x + left.width,
        leftMinPx: low,
        leftMaxPx: high,
        leftPx: left.width,
        pairPx: pair,
        space: pairFr > 0 ? pair / pairFr : Math.max(1, pair),
      });
    }

    out.push({
      id: row.id,
      kind: row.kind,
      top,
      height,
      template: tracks.join(` ${gutter}px `),
      free,
      cells,
      seams,
    });
    top += height + gutter;
  }

  return {
    rows: out,
    template: heights.map((px) => `${px}px`).join(` ${gutter}px `),
    contentHeight: heights.reduce((carry, px) => carry + px, 0) + bands,
    flexSpace,
    spanHeight,
  };
}
