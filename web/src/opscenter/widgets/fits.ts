
import { kindOf, metaFor, META } from '../engine/meta';
import type { CellId, CellMeta, InstanceKind, LayoutPage, SlotId } from '../engine/types';
import { FIT_DECLARATIONS, pluginDeclarationFor } from './fit-declarations';
import { GRID_SIZE_NAMES, namedSize, type NamedFitSize } from './named-sizes';
import type { FitSize, FitZone, WidgetFits } from './types';

export const SIZE_UNIT_PX: Readonly<FitSize> = Object.freeze({ w: 96, h: 64 });

export const FIT_TOLERANCE_PX = 4;

type Axis = 'w' | 'h';

export function unitsOf(px: number, axis: Axis): number {
  return Math.max(1, Math.round(Math.max(0, px) / SIZE_UNIT_PX[axis]));
}

export function unitsCovering(px: number, axis: Axis): number {
  return Math.max(1, Math.ceil(px / SIZE_UNIT_PX[axis] + 0.5));
}

export function unitsOfBox(box: { width: number; height: number }): FitSize {
  return { w: unitsOf(box.width, 'w'), h: unitsOf(box.height, 'h') };
}

export function minFitFor(meta: Pick<CellMeta, 'minPx' | 'minHeight'>): FitSize {
  return {
    w: unitsOf(meta.minPx - FIT_TOLERANCE_PX, 'w'),
    h: unitsOf(meta.minHeight - FIT_TOLERANCE_PX, 'h'),
  };
}

export const TESTED_TOLERANCE = 0.25;

export function fitsFor(key: CellId | InstanceKind, meta: CellMeta): WidgetFits {
  const declared = FIT_DECLARATIONS[key] ?? pluginDeclarationFor(key);
  if (!declared) throw new Error(`opscenter: no fit declaration for ${key}`);
  return {
    min: minFitFor(meta),
    sizes: declared.sizes,
    anySize: declared.anySize,
    ...(declared.max_per_surface === undefined ? {} : { max_per_surface: declared.max_per_surface }),
  };
}

export function suggestedSizes(fits: Pick<WidgetFits, 'sizes'>): NamedFitSize[] {
  return GRID_SIZE_NAMES.filter((name) => fits.sizes.includes(name)).map(namedSize);
}

export function zoneOfPage(page: LayoutPage, popout: boolean): FitZone {
  if (page === 'warroom') return 'terminal';
  return page === 'home' && popout ? 'popout' : page;
}

export function isPopoutWindow(): boolean {
  return typeof document !== 'undefined' && document.getElementById('popout-screen') !== null;
}

export function smallestFit(fits: WidgetFits, at: FitSize | null): FitSize {
  return at ? { w: Math.max(at.w, fits.min.w), h: Math.max(at.h, fits.min.h) } : fits.min;
}

export type MisfitReason = 'too-small' | 'untested';

export type FitCheck =
  | { ok: true }
  | { ok: false; reason: MisfitReason; has: FitSize | null; suggest: FitSize | null };

export interface TestedEnvelope {
  width: [number, number];
  height: [number, number];
  aspect: [number, number];
}

export function testedEnvelope(tested: readonly FitSize[]): TestedEnvelope {
  const boxes = tested.map((size) => ({ w: size.w * SIZE_UNIT_PX.w, h: size.h * SIZE_UNIT_PX.h }));
  const widths = boxes.map((box) => box.w);
  const heights = boxes.map((box) => box.h);
  const aspects = boxes.map((box) => box.w / box.h);
  const low = 1 - TESTED_TOLERANCE;
  const high = 1 + TESTED_TOLERANCE;
  return {
    width: [Math.min(...widths) * low, Math.max(...widths) * high],
    height: [Math.min(...heights) * low, Math.max(...heights) * high],
    aspect: [Math.min(...aspects) / high, Math.max(...aspects) * high],
  };
}

export function testedBox(fits: Pick<WidgetFits, 'sizes' | 'anySize'>, box: { width: number; height: number }): boolean {
  if (fits.anySize || fits.sizes.length === 0) return true;
  const span = testedEnvelope(suggestedSizes(fits));
  const inside = (value: number, [lo, hi]: [number, number]): boolean => value >= lo && value <= hi;
  return inside(box.width, span.width) && inside(box.height, span.height) && inside(box.width / box.height, span.aspect);
}

export function checkFit(fits: WidgetFits, box: { width: number; height: number } | null): FitCheck {
  if (!box || box.width <= 0 || box.height <= 0) return { ok: true };
  const has = unitsOfBox(box);
  if (has.w < fits.min.w || has.h < fits.min.h) return { ok: false, reason: 'too-small', has, suggest: smallestFit(fits, has) };
  if (testedBox(fits, box)) return { ok: true };
  return { ok: false, reason: 'untested', has, suggest: nearestTested(fits, has) };
}

export function nearestTested(fits: Pick<WidgetFits, 'sizes'>, at: FitSize): NamedFitSize | null {
  let best: NamedFitSize | null = null;
  let gap = Infinity;
  for (const size of suggestedSizes(fits)) {
    const distance = Math.abs(size.w - at.w) + Math.abs(size.h - at.h);
    if (distance < gap) {
      best = size;
      gap = distance;
    }
  }
  return best;
}

export function fitsForSlot(slotId: SlotId): WidgetFits | null {
  const key = (kindOf(slotId) ?? slotId) as CellId | InstanceKind;
  if (!(FIT_DECLARATIONS[key] ?? pluginDeclarationFor(key))) return null;
  return fitsFor(key, metaFor(slotId, META));
}
