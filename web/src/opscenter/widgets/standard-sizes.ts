/* padding */

import { DEFAULT_WIDTH_PX } from '../../lib/drawer/resize';

const MIN_WIDTH_PX = 240;
const MAX_WIDTH_PX = 480;
import { SIZE_UNIT_PX } from './fits';
import type { GridSizeName, NamedFitSize } from './named-sizes';
import type { FitSize, FitZone } from './types';

export type SizeName = 's' | 'm' | 'l' | 'phone' | 'glance' | OffSizeName | GridSizeName;

export type OffSizeName = 'odd-wide' | 'odd-tall' | 'odd-mid';

export const OFF_SIZES: Readonly<Record<OffSizeName, Readonly<FitSize>>> = Object.freeze({
  'odd-wide': Object.freeze({ w: 957, h: 23 }),
  'odd-tall': Object.freeze({ w: 37, h: 413 }),
  'odd-mid': Object.freeze({ w: 173, h: 101 }),
});

export const DRAWER_ODD_WIDTH_PX = 277;

export interface StandardSize {
  name: SizeName;
  w: number;
  h: number | null;
  viewport: number;
  declared?: boolean;
}

export const MIDDLE_UNITS: Readonly<FitSize> = Object.freeze({ w: 4, h: 4 });

export const LARGE_CAP_PX: Readonly<FitSize> = Object.freeze({ w: 1440, h: 960 });

/* padding */
export const GLANCE_ROW_PADDING_PX = 4;

export const DESKTOP_VIEWPORT_PX = 1600;

export const PHONE_VIEWPORT_PX = 390;
export const PHONE_GUTTER_PX = 16;

export interface CellFloor {
  minPx: number;
  minHeight: number;
}

function px(size: FitSize): FitSize {
  return { w: size.w * SIZE_UNIT_PX.w, h: size.h * SIZE_UNIT_PX.h };
}

export function standardSizes(
  floor: CellFloor,
  zone: FitZone,
  glanceHeight: number | null = null,
  named: readonly NamedFitSize[] = [],
): StandardSize[] {
  const desk = DESKTOP_VIEWPORT_PX;
  if (zone === 'drawer') {
    const sizes: StandardSize[] = [
      { name: 's', w: MIN_WIDTH_PX, h: null, viewport: desk },
      { name: 'm', w: DEFAULT_WIDTH_PX, h: null, viewport: desk },
      { name: 'l', w: MAX_WIDTH_PX, h: null, viewport: desk },
      { name: 'odd-mid', w: DRAWER_ODD_WIDTH_PX, h: null, viewport: desk },
    ];
    if (glanceHeight !== null) {
      sizes.push({ name: 'glance', w: DEFAULT_WIDTH_PX, h: glanceHeight + GLANCE_ROW_PADDING_PX, viewport: desk });
    }
    return sizes;
  }
  const phone: StandardSize = { name: 'phone', w: PHONE_VIEWPORT_PX - 2 * PHONE_GUTTER_PX, h: null, viewport: PHONE_VIEWPORT_PX };
  const l = { ...LARGE_CAP_PX };
  const s = { w: floor.minPx, h: floor.minHeight };
  const middle = px(MIDDLE_UNITS);
  const m = { w: Math.max(middle.w, s.w), h: Math.max(middle.h, s.h) };
  const off = (name: OffSizeName): StandardSize => ({ name, w: s.w + OFF_SIZES[name].w, h: s.h + OFF_SIZES[name].h, viewport: desk });
  const units = named.map((size): StandardSize => {
    const box = px(size);
    return { name: size.name, w: Math.max(box.w, s.w), h: Math.max(box.h, s.h), viewport: desk, declared: true };
  });
  return [
    { name: 's', ...s, viewport: desk },
    { name: 'm', ...m, viewport: desk },
    { name: 'l', ...l, viewport: desk },
    phone,
    ...units,
    off('odd-wide'),
    off('odd-tall'),
    off('odd-mid'),
  ];
}
