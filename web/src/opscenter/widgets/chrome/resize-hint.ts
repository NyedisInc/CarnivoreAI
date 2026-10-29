
import { FIT_TOLERANCE_PX, unitsCovering, unitsOf } from '../fits';
import type { FitSize } from '../types';

export type AxisMove = 'grow' | 'shrink' | null;

export interface ResizeGuide {
  w: AxisMove;
  h: AxisMove;
}

export const SWITCH_MARGIN = 2;

export function axisMove(has: number, target: number): AxisMove {
  return target > has ? 'grow' : target < has ? 'shrink' : null;
}

/* there is nothing */
export function resizeGuide(has: FitSize | null, target: FitSize | null): ResizeGuide | null {
  if (!has || !target) return null;
  const guide = { w: axisMove(has.w, target.w), h: axisMove(has.h, target.h) };
  return guide.w || guide.h ? guide : null;
}

export function sizeDistance(a: FitSize, b: FitSize): number {
  return Math.abs(a.w - b.w) + Math.abs(a.h - b.h);
}

export function sameSize(a: FitSize, b: FitSize): boolean {
  return a.w === b.w && a.h === b.h;
}

export function guideFloor(
  recordMin: FitSize,
  rowFloorPx: number | null,
  bodyFloorPx: { width: number; height: number } | null,
  titleRowPx: number,
): FitSize {
  const rowH = rowFloorPx === null ? 1 : unitsOf(rowFloorPx - FIT_TOLERANCE_PX, 'h');
  const bodyW = bodyFloorPx ? unitsCovering(bodyFloorPx.width - FIT_TOLERANCE_PX, 'w') : 1;
  const bodyH = bodyFloorPx ? unitsCovering(bodyFloorPx.height + titleRowPx - FIT_TOLERANCE_PX, 'h') : 1;
  return { w: Math.max(recordMin.w, bodyW), h: Math.max(recordMin.h, rowH, bodyH) };
}

export interface WidthReach {
  row: number;
  narrowest: number;
  widest: number;
}

export function widthReach(rowPx: number, gutterPx: number, neighbourFloorsPx: readonly number[]): WidthReach {
  const shared = rowPx - gutterPx * neighbourFloorsPx.length;
  const row = unitsOf(shared, 'w');
  if (neighbourFloorsPx.length === 0) return { row, narrowest: row, widest: row };
  return { row, narrowest: 1, widest: unitsOf(shared - neighbourFloorsPx.reduce((sum, px) => sum + px, 0), 'w') };
}

export function guideCandidates(declared: readonly FitSize[], floor: FitSize, reach: WidthReach | null): FitSize[] {
  const out: FitSize[] = [];
  for (const size of declared) {
    const drawn = reach && size.w > reach.row ? { w: reach.row, h: size.h } : { w: size.w, h: size.h };
    if (drawn.w < floor.w || drawn.h < floor.h) continue;
    if (reach && (drawn.w < reach.narrowest || drawn.w > reach.widest)) continue;
    if (!out.some((one) => sameSize(one, drawn))) out.push(drawn);
  }
  return out;
}

export function pickTarget(held: FitSize | null, has: FitSize, candidates: readonly FitSize[]): FitSize | null {
  if (candidates.length === 0 || candidates.some((size) => sameSize(size, has))) return null;
  let nearest = candidates[0]!;
  for (const size of candidates) if (sizeDistance(size, has) < sizeDistance(nearest, has)) nearest = size;
  const keep = held && candidates.some((size) => sameSize(size, held));
  if (keep && sizeDistance(held, has) - sizeDistance(nearest, has) < SWITCH_MARGIN) return held;
  return nearest;
}

export type GuideEdge = 'top' | 'right' | 'bottom' | 'left';

export type ChevronDirection = 'up' | 'right' | 'down' | 'left';

export function guideChevrons(guide: ResizeGuide | null): { edge: GuideEdge; point: ChevronDirection }[] {
  if (!guide) return [];
  const out: { edge: GuideEdge; point: ChevronDirection }[] = [];
  if (guide.h) {
    out.push({ edge: 'top', point: guide.h === 'grow' ? 'up' : 'down' });
    out.push({ edge: 'bottom', point: guide.h === 'grow' ? 'down' : 'up' });
  }
  if (guide.w) {
    out.push({ edge: 'left', point: guide.w === 'grow' ? 'left' : 'right' });
    out.push({ edge: 'right', point: guide.w === 'grow' ? 'right' : 'left' });
  }
  return out;
}
