
import type { FitSize } from './types';

export const GRID_SIZE_NAMES = ['small', 'wide', 'tall', 'medium', 'large', 'full'] as const;

export type GridSizeName = (typeof GRID_SIZE_NAMES)[number];

export type WidgetSizeName = GridSizeName | 'glance';

export const NAMED_SIZE_UNITS: Readonly<Record<GridSizeName, Readonly<FitSize>>> = Object.freeze({
  small: Object.freeze({ w: 1, h: 1 }),
  wide: Object.freeze({ w: 2, h: 1 }),
  tall: Object.freeze({ w: 2, h: 4 }),
  medium: Object.freeze({ w: 4, h: 4 }),
  large: Object.freeze({ w: 6, h: 5 }),
  full: Object.freeze({ w: 12, h: 5 }),
});

export interface NamedFitSize extends FitSize {
  name: GridSizeName;
}

export function isGridSizeName(value: unknown): value is GridSizeName {
  return typeof value === 'string' && (GRID_SIZE_NAMES as readonly string[]).includes(value);
}

export function namedSize(name: GridSizeName): NamedFitSize {
  const units = NAMED_SIZE_UNITS[name];
  return { name, w: units.w, h: units.h };
}

export function namesAtOrAbove(min: FitSize): GridSizeName[] {
  const fits = GRID_SIZE_NAMES.filter((name) => NAMED_SIZE_UNITS[name].w >= min.w && NAMED_SIZE_UNITS[name].h >= min.h);
  return fits.length > 0 ? fits : ['full'];
}

export function sizeNameKey(name: WidgetSizeName): string {
  return `widgets.size.${name}`;
}

export function sizeHintKey(name: WidgetSizeName): string {
  return `widgets.size.${name}.hint`;
}
