import type { Rect } from '../../../lib/motion-grid';
import { ROW_MIN } from '../floors';
import type { Layout, SlotId } from '../types';
import { layoutGeometry } from './layout-rects';
import { layoutFromRects } from './rects-to-rows';

export interface Fit {
  width: number;
  height: number;
  gutter: number;
}

export interface Stretch {
  above: readonly SlotId[];
  below: readonly SlotId[];
}

export function moveBoundary(layout: Layout, seg: Stretch, dy: number, fit: Fit): Layout | null {
  if (layout.rows.length === 0 || !layout.rows.every((row) => row.kind === 'flex')) return null;
  const geo = layoutGeometry(layout, fit.width, fit.height, fit.gutter);
  const above = seg.above.map((id) => geo.rects.get(id));
  const below = seg.below.map((id) => geo.rects.get(id));
  if (above.length === 0 || below.length === 0 || above.some((one) => !one) || below.some((one) => !one)) return null;
  const up = Math.max(0, Math.min(...above.map((one) => one!.h - ROW_MIN)));
  const down = Math.max(0, Math.min(...below.map((one) => one!.h - ROW_MIN)));
  const move = Math.round(Math.max(-up, Math.min(down, dy)));
  if (move === 0) return layout;
  const rects = new Map<SlotId, Rect>(geo.rects);
  for (const id of seg.above) rects.set(id, { ...rects.get(id)!, h: rects.get(id)!.h + move });
  for (const id of seg.below) rects.set(id, { ...rects.get(id)!, y: rects.get(id)!.y + move, h: rects.get(id)!.h - move });
  return layoutFromRects(layout, rects, fit.gutter, geo.tracks.rows.map((row) => row.top));
}
