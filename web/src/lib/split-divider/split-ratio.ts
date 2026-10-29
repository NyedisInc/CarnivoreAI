
export type SplitAxis = 'x' | 'y';

export interface RatioBounds {
  min: number;
  max: number;
  step: number;
}

export function clampSplit(ratio: number, bounds: RatioBounds): number {
  if (!Number.isFinite(ratio)) return (bounds.min + bounds.max) / 2;
  return Math.min(bounds.max, Math.max(bounds.min, ratio));
}

export function ratioAtPointer(axis: SplitAxis, x: number, y: number, box: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>, bounds: RatioBounds): number {
  const length = axis === 'y' ? box.height : box.width;
  if (length <= 0) return clampSplit(Number.NaN, bounds);
  const along = axis === 'y' ? y - box.top : x - box.left;
  return clampSplit(along / length, bounds);
}

export function ratioAfterKey(axis: SplitAxis, key: string, ratio: number, bounds: RatioBounds, reset: number): number | null {
  const back = axis === 'y' ? 'ArrowUp' : 'ArrowLeft';
  const forward = axis === 'y' ? 'ArrowDown' : 'ArrowRight';
  if (key === back) return clampSplit(Math.round((ratio - bounds.step) * 1000) / 1000, bounds);
  if (key === forward) return clampSplit(Math.round((ratio + bounds.step) * 1000) / 1000, bounds);
  if (key === 'Home') return clampSplit(reset, bounds);
  return null;
}
