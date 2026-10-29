import type { WidgetFits } from './types';

export type WidgetSizeClass = 'small' | 'medium' | 'large';

export const SIZE_CLASS_LIMITS: Readonly<Record<'small' | 'medium', number>> = Object.freeze({ small: 2, medium: 4 });

export const NO_SHOW_THRESHOLDS: Readonly<Record<WidgetSizeClass, Readonly<{ width: number; height: number }>>> = Object.freeze({
  small: Object.freeze({ width: 96, height: 48 }),
  medium: Object.freeze({ width: 160, height: 96 }),
  large: Object.freeze({ width: 220, height: 128 }),
});

export function sizeClassOf(fits: Pick<WidgetFits, 'min'>): WidgetSizeClass {
  const side = Math.max(fits.min.w, fits.min.h);
  if (side <= SIZE_CLASS_LIMITS.small) return 'small';
  return side <= SIZE_CLASS_LIMITS.medium ? 'medium' : 'large';
}

export function isNoShow(fits: Pick<WidgetFits, 'min'>, box: { width: number; height: number } | null): boolean {
  if (!box || box.width <= 0 || box.height <= 0) return false;
  const limit = NO_SHOW_THRESHOLDS[sizeClassOf(fits)];
  return box.width < limit.width || box.height < limit.height;
}
