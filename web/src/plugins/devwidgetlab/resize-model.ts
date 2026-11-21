import type { LabSize } from '../sdk/widget-lab';

export interface Box {
  w: number;
  h: number;
}

export type ResizeAxis = 'e' | 's' | 'se' | 'w' | 'n';

export const MIN_BOX: Readonly<Box> = Object.freeze({ w: 120, h: 80 });
export const MAX_BOX: Readonly<Box> = Object.freeze({ w: 2400, h: 1800 });
export const KEY_STEP_PX = 8;
export const KEY_STEP_BIG_PX = 32;

export function clampBox(box: Box): Box {
  const within = (value: number, min: number, max: number): number => Math.min(max, Math.max(min, Math.round(value)));
  return { w: within(box.w, MIN_BOX.w, MAX_BOX.w), h: within(box.h, MIN_BOX.h, MAX_BOX.h) };
}

export function dragBox(start: Box, dx: number, dy: number, axis: ResizeAxis, scale: number): Box {
  const per = scale > 0 ? scale : 1;
  const wide = axis === 'w' ? start.w - dx / per : axis === 's' || axis === 'n' ? start.w : start.w + dx / per;
  const tall = axis === 'n' ? start.h - dy / per : axis === 'e' || axis === 'w' ? start.h : start.h + dy / per;
  return clampBox({ w: wide, h: tall });
}

export function stepBox(box: Box, key: string, big: boolean, axis: ResizeAxis = 'se'): Box | null {
  const step = big ? KEY_STEP_BIG_PX : KEY_STEP_PX;
  if (axis === 'w') return key === 'ArrowLeft' ? clampBox({ ...box, w: box.w + step }) : key === 'ArrowRight' ? clampBox({ ...box, w: box.w - step }) : null;
  if (axis === 'n') return key === 'ArrowUp' ? clampBox({ ...box, h: box.h + step }) : key === 'ArrowDown' ? clampBox({ ...box, h: box.h - step }) : null;
  if (key === 'ArrowRight') return clampBox({ ...box, w: box.w + step });
  if (key === 'ArrowLeft') return clampBox({ ...box, w: box.w - step });
  if (key === 'ArrowDown') return clampBox({ ...box, h: box.h + step });
  if (key === 'ArrowUp') return clampBox({ ...box, h: box.h - step });
  return null;
}

export function nearestSize(sizes: readonly LabSize[], box: Box): LabSize | null {
  const distance = (size: LabSize): number => Math.abs(box.w - size.w) / size.w + (size.h === null ? 0 : Math.abs(box.h - size.h) / size.h);
  let best: LabSize | null = null;
  for (const size of sizes) if (best === null || distance(size) < distance(best)) best = size;
  return best;
}

export function sameBox(a: Box, b: Box): boolean {
  return a.w === b.w && a.h === b.h;
}
