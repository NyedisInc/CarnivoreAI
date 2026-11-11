import type { Rect } from '../../../lib/motion-grid';
import { COL_MIN } from '../floors';
import { META } from '../meta';
import { computeTracks, type SurfaceTracks } from '../tracks';
import type { CellTarget, RowTarget } from '../pointer';
import type { Layout, SlotId } from '../types';

export interface SurfaceGeometry {
  tracks: SurfaceTracks;
  rects: Map<SlotId, Rect>;
}

export function layoutGeometry(layout: Layout, width: number, height: number, gutter: number): SurfaceGeometry {
  const tracks = computeTracks({ rows: layout.rows, width, height, gutter, metas: META });
  const rects = new Map<SlotId, Rect>();
  for (const row of tracks.rows) {
    for (const cell of row.cells) {
      if (cell.slotId === null) continue;
      const h = cell.span >= 2 ? (tracks.spanHeight.get(cell.slotId) ?? row.height) : row.height;
      rects.set(cell.slotId, { x: cell.x, y: row.top, w: cell.width, h });
    }
  }
  return { tracks, rects };
}

export function contentExtent(layout: Layout, tracks: SurfaceTracks): number | null {
  return layout.rows.length > 0 && layout.rows.every((row) => row.kind === 'px') ? tracks.contentHeight : null;
}

export function dropGeometry(layout: Layout, tracks: SurfaceTracks): { rows: RowTarget[]; cells: CellTarget[] } {
  const rows: RowTarget[] = [];
  const cells: CellTarget[] = [];
  layout.rows.forEach((row, at) => {
    const drawn = tracks.rows[at];
    if (!drawn) return;
    const centres: number[] = [];
    const reserved: [number, number][] = [];
    for (const cell of drawn.cells) {
      centres.push(cell.x + cell.width / 2);
      if (cell.slotId === null) reserved.push([cell.x, cell.x + cell.width]);
      else {
        const h = cell.span >= 2 ? (tracks.spanHeight.get(cell.slotId) ?? drawn.height) : drawn.height;
        cells.push({ id: cell.slotId, left: cell.x, right: cell.x + cell.width, top: drawn.top, bottom: drawn.top + h });
      }
    }
    rows.push({ id: row.id, top: drawn.top, bottom: drawn.top + drawn.height, centres, reserved });
  });
  return { rows, cells };
}

export function uncoveredFraction(rects: readonly { x: number; y: number; w: number; h: number }[], width: number, height: number, gutter: number): number {
  const xs = [0, width, ...rects.flatMap((r) => [r.x, r.x + r.w])].sort((a, b) => a - b);
  const ys = [0, height, ...rects.flatMap((r) => [r.y, r.y + r.h])].sort((a, b) => a - b);
  let hole = 0;
  for (let i = 0; i < xs.length - 1; i += 1) {
    const w = xs[i + 1]! - xs[i]!;
    if (w <= gutter + 1) continue;
    for (let j = 0; j < ys.length - 1; j += 1) {
      const h = ys[j + 1]! - ys[j]!;
      if (h <= gutter + 1) continue;
      const cx = xs[i]! + w / 2;
      const cy = ys[j]! + h / 2;
      if (!rects.some((r) => cx > r.x && cx < r.x + r.w && cy > r.y && cy < r.y + r.h)) hole += w * h;
    }
  }
  return hole / (width * height);
}

const MIN_WIDTH = COL_MIN;

const MIN_HEIGHT = 120;

const MAX_HOLE = 0.01;

export function rectsAreSound(rects: readonly { x: number; y: number; w: number; h: number }[], width: number, height: number, gutter: number): boolean {
  for (let i = 0; i < rects.length; i += 1) {
    const a = rects[i]!;
    if (a.x < -1 || a.x + a.w > width + 1 || a.w < MIN_WIDTH || a.h < MIN_HEIGHT) return false;
    for (let j = i + 1; j < rects.length; j += 1) {
      const b = rects[j]!;
      if (a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1) return false;
    }
  }
  return uncoveredFraction(rects, width, height, gutter) <= MAX_HOLE;
}

export function dropLeavesNothingWorse(before: ReadonlyMap<string, Rect>, after: ReadonlyMap<string, Rect>, active: string, of: string, horizontal: boolean): boolean {
  const rects = [...after.values()];
  for (let i = 0; i < rects.length; i += 1) {
    const a = rects[i]!;
    for (let j = i + 1; j < rects.length; j += 1) {
      const b = rects[j]!;
      if (a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1) return false;
    }
  }
  const arrival = after.get(active);
  const target = after.get(of);
  const extent = arrival && target ? (horizontal ? arrival.w + target.w : arrival.h + target.h) + 9 : 0;
  for (const [id, r] of after) {
    const pair = id === active || id === of;
    const was = before.get(id);
    const wideOk = pair ? !horizontal || extent < MIN_WIDTH : !!was && was.w < MIN_WIDTH;
    const highOk = pair ? horizontal || extent < MIN_HEIGHT : !!was && was.h < MIN_HEIGHT;
    if (r.w < MIN_WIDTH - 2 && !wideOk) return false;
    if (r.h < MIN_HEIGHT - 2 && !highOk) return false;
  }
  return true;
}
