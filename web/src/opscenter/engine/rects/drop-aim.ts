import type { Rect } from '../../../lib/motion-grid';
import type { DropTarget } from '../layout.svelte';
import type { GrammarTarget, SnapRow, SnapStrip, SnapWindow, Snapshot } from '../drop-grammar';
import type { StripTarget } from '../tab-drag';
import type { SlotId } from '../types';
import type { SurfaceGeometry } from './layout-rects';

export function buildSnapshot(
  geo: SurfaceGeometry,
  box: { width: number; height: number },
  gutter: number,
  strips: readonly StripTarget[],
  origin: { left: number; top: number },
  takesTabs: boolean,
): Snapshot {
  const rows: SnapRow[] = geo.tracks.rows.map((row) => ({
    id: row.id,
    top: row.top,
    height: row.height,
    cells: row.cells.map((c) => ({ owner: c.slotId ?? c.of ?? null, x: c.x, width: c.width })),
  }));
  const windows: SnapWindow[] = [];
  for (const [id, rect] of geo.rects) {
    const s = strips.find((one) => one.slot === id);
    const strip: SnapStrip | null = s
      ? {
          x: s.left - origin.left,
          y: s.top - origin.top,
          w: s.right - s.left,
          h: s.bottom - s.top,
          tabs: s.tabs.map((tab) => ({ id: tab.id, centre: tab.centre - origin.left })),
        }
      : null;
    windows.push({ id, ...rect, takesTabs: takesTabs && strip !== null, tabs: s?.tabs.map((tab) => tab.id) ?? [], strip });
  }
  return { width: box.width, height: box.height, gutter, rows, windows };
}

export function toDropTarget(target: GrammarTarget, width: number, height?: number): DropTarget | null {
  switch (target.kind) {
    case 'split':
      return { kind: 'split', of: target.of as SlotId, side: target.side, width, height };
    case 'stack':
      return { kind: 'stack', of: target.of as SlotId, edge: target.edge, width, height };
    case 'seam':
      return { kind: 'seam', rows: target.rows as never, width, height };
    case 'new':
      return { kind: 'new', after: target.after as never };
    case 'stack-run':
      return { kind: 'stack-run', of: target.of as SlotId[], edge: target.edge };
    default:
      return null;
  }
}

export function sameRects(a: ReadonlyMap<string, Rect>, b: ReadonlyMap<string, Rect>): boolean {
  if (a.size !== b.size) return false;
  for (const [id, r] of a) {
    const o = b.get(id);
    if (!o || Math.abs(o.x - r.x) > 1 || Math.abs(o.y - r.y) > 1 || Math.abs(o.w - r.w) > 1 || Math.abs(o.h - r.h) > 1) return false;
  }
  return true;
}
