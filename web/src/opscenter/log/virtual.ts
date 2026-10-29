
export const OVERSCAN = 12;

export interface Layout {
  offsets: Float64Array;
}

export function layout(ids: readonly string[], rowPx: number, heights: ReadonlyMap<string, number>): Layout {
  const offsets = new Float64Array(ids.length + 1);
  for (let i = 0; i < ids.length; i += 1) {
    offsets[i + 1] = (offsets[i] as number) + (heights.get(ids[i] as string) ?? rowPx);
  }
  return { offsets };
}

export function windowAt(lay: Layout, scrollTop: number, viewport: number): { start: number; end: number } {
  const offsets = lay.offsets;
  const count = offsets.length - 1;
  if (count <= 0) return { start: 0, end: 0 };
  let lo = 0;
  let hi = count - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if ((offsets[mid] as number) <= scrollTop) lo = mid;
    else hi = mid - 1;
  }
  let end = lo;
  const bottom = scrollTop + viewport;
  while (end < count && (offsets[end] as number) < bottom) end += 1;
  return { start: Math.max(0, lo - OVERSCAN), end: Math.min(count, end + OVERSCAN) };
}
