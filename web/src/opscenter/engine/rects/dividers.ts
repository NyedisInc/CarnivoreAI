import type { Rect } from '../../../lib/motion-grid';
import { META } from '../meta';
import { resizeColumns, resizeRows } from '../model';
import { boundarySegments, type BoundarySegment } from '../row-handles';
import { edgeBox, spanCorners, spanEdges } from '../span-edges';
import type { SeamTrack, SurfaceTracks } from '../tracks';
import type { Layout, RowId } from '../types';
import { extraSpecs } from './edge-fill';
import { layoutGeometry } from './layout-rects';
import { moveBoundary, type Fit, type Stretch } from './boundary-move';

export type DividerKind = 'col' | 'row' | 'inter' | 'corner' | 'tail';

export interface DividerSpec {
  id: string;
  kind: DividerKind;
  rect: Rect;
  rowId: RowId;
  seam?: SeamTrack;
  boundary?: RowId;
  free: number;
  rowFree: number;
  flexSpace: number;
  tail?: number;
  mirror: boolean;
  seg?: Stretch;
  fit?: Fit;
  diag?: 'nesw';
}

const SQUARE = 14;

export function dividerSpecs(
  layout: Layout,
  tracks: SurfaceTracks,
  box: { width: number; height: number },
  gutter: number,
  wide: boolean,
): DividerSpec[] {
  if (!wide) return [];
  const rows = layout.rows;
  const out: DividerSpec[] = [];
  const edges = spanEdges(tracks, rows.map((row) => row.id));
  const corners = spanCorners(tracks, rows.map((row) => row.id), edges);
  const isSpanEdge = (at: number, afterVisual: number): boolean =>
    edges.some((edge) => edge.rowAt === at && edge.seam.afterVisual === afterVisual);
  const crossed = (at: number): [number, number][] =>
    (tracks.rows[at + 1]?.cells ?? []).filter((cell) => cell.reserved).map((cell) => [cell.x, cell.x + cell.width] as [number, number]);
  const fit: Fit = { width: box.width, height: box.height, gutter };
  const base = { flexSpace: tracks.flexSpace, mirror: false, fit };
  const stretchAt = (at: number, x0: number, x1: number): Stretch | undefined => {
    const hit = boundarySegments(tracks, at, box.width, gutter).filter((one) => one.left < x1 && one.left + one.width > x0);
    return hit.length ? { above: hit.flatMap((one) => one.above), below: hit.flatMap((one) => one.below) } : undefined;
  };
  const key = (seg: Stretch | undefined, fallback: string): string => (seg ? `${seg.above[0]}>${seg.below[0]}` : fallback);
  const idOf = (row: RowId, index: number): string => rows.find((one) => one.id === row)?.slots[index]?.id ?? `${row}:${index}`;
  const square = (x: number, bandTop: number): Rect => ({
    x: Math.round(x + gutter / 2 - SQUARE / 2),
    y: Math.round(bandTop + gutter / 2 - SQUARE / 2),
    w: SQUARE,
    h: SQUARE,
  });

  rows.forEach((row, at) => {
    const drawn = tracks.rows[at];
    if (!drawn) return;
    for (const seam of drawn.seams) {
      out.push({
        ...base,
        id: `col:${row.id}:${seam.index}`,
        kind: 'col',
        rect: { x: seam.x, y: drawn.top, w: gutter, h: drawn.height },
        rowId: row.id,
        seam,
        free: seam.space,
        rowFree: drawn.free,
      });
    }
    if (at >= rows.length - 1) return;
    const bandTop = drawn.top + drawn.height;
    for (const segment of boundarySegments(tracks, at, box.width, gutter)) {
      const seg: Stretch = { above: segment.above, below: segment.below };
      out.push({ ...base, id: `row:${key(seg, row.id)}`, kind: 'row', rect: { x: segment.left, y: bandTop, w: segment.width, h: gutter }, rowId: row.id, seg, free: drawn.free, rowFree: drawn.free });
    }
    for (const seam of drawn.seams) {
      if (crossed(at).some(([start, end]) => seam.x >= start && seam.x <= end) || isSpanEdge(at, seam.afterVisual)) continue;
      const mark = square(seam.x, bandTop);
      const seg = stretchAt(at, mark.x, mark.x + mark.w);
      out.push({ ...base, id: `int:${idOf(row.id, seam.index)}|${idOf(row.id, seam.index + 1)}`, kind: 'inter', rect: mark, rowId: row.id, seam, seg, free: drawn.free, rowFree: drawn.free });
    }
  });
  for (const corner of corners) {
    const above = tracks.rows[corner.bandAt];
    const home = tracks.rows[rows.findIndex((row) => row.id === corner.seamRow)];
    if (!above || !home) continue;
    const mark = square(corner.seam.x, above.top + above.height);
    const seg = stretchAt(corner.bandAt, mark.x, mark.x + mark.w);
    out.push({
      ...base,
      id: `cor:${idOf(corner.seamRow, corner.seam.index)}|${idOf(corner.seamRow, corner.seam.index + 1)}:${key(seg, corner.boundaryRow)}`,
      kind: 'corner',
      seg,
      rect: mark,
      rowId: corner.seamRow,
      boundary: corner.boundaryRow,
      seam: corner.seam,
      free: home.free,
      rowFree: home.free,
    });
  }
  const last = rows[rows.length - 1];
  const lastDrawn = tracks.rows[rows.length - 1];
  if (last && last.kind === 'px' && lastDrawn) {
    const tail = Math.max(0, box.height - (tracks.contentHeight - Math.max(1, Math.round(last.size))));
    out.push({
      ...base,
      id: 'tail',
      kind: 'tail',
      rect: { x: 0, y: lastDrawn.top + lastDrawn.height, w: box.width, h: gutter },
      rowId: last.id,
      free: 0,
      rowFree: 0,
      tail,
    });
  }
  for (const edge of edges) {
    const edgeRect = edgeBox(tracks, edge);
    out.push({
      ...base,
      id: `edge:${edge.rowId}:${edge.seam.index}`,
      kind: 'col',
      rect: { x: Math.round(edge.seam.x), y: Math.round(edgeRect.top), w: gutter, h: Math.round(edgeRect.height) },
      rowId: edge.rowId,
      seam: edge.seam,
      free: edge.seam.space,
      rowFree: tracks.rows[edge.rowAt]?.free ?? 1,
      mirror: true,
    });
  }
  return inDrawOrder([...out, ...extraSpecs(out, new Map(layoutGeometry(layout, box.width, box.height, gutter).rects), box, gutter)]);
}

const RANK: Record<DividerKind, number> = { col: 0, row: 1, tail: 1, inter: 2, corner: 2 };

function inDrawOrder(specs: DividerSpec[]): DividerSpec[] {
  const rank = (spec: DividerSpec): number => (spec.mirror ? 3 : RANK[spec.kind]);
  return specs.sort((a, b) => rank(a) - rank(b) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

function tailDelta(base: Layout, spec: DividerSpec, dy: number): number {
  const size = base.rows.find((entry) => entry.id === spec.rowId)?.size ?? 0;
  return Math.max(dy, Math.min(0, (spec.tail ?? 0) - size));
}

function boundaryMove(base: Layout, spec: DividerSpec, dy: number): Layout | null {
  return spec.seg && spec.fit ? moveBoundary(base, spec.seg, dy, spec.fit) : null;
}

function both(base: Layout, spec: DividerSpec, dx: number, dy: number, boundary: RowId): Layout {
  const seam = spec.seam!;
  const columns = resizeColumns(base, spec.rowId, seam.index, dx, spec.free, seam.leftMinPx, seam.leftMaxPx);
  return boundaryMove(columns, spec, dy) ?? resizeRows(columns, boundary, dy, spec.flexSpace, META);
}

export function applyDivider(base: Layout, spec: DividerSpec, dx: number, dy: number): Layout {
  const seam = spec.seam;
  switch (spec.kind) {
    case 'col':
      return seam ? resizeColumns(base, spec.rowId, seam.index, dx, spec.free, seam.leftMinPx, seam.leftMaxPx) : base;
    case 'row':
      return boundaryMove(base, spec, dy) ?? resizeRows(base, spec.rowId, dy, spec.flexSpace, META);
    case 'tail':
      return resizeRows(base, spec.rowId, tailDelta(base, spec, dy), spec.flexSpace, META);
    case 'inter':
      return seam ? both(base, spec, dx, dy, spec.rowId) : base;
    case 'corner':
      return seam && spec.boundary ? both(base, spec, dx, dy, spec.boundary) : base;
  }
}
