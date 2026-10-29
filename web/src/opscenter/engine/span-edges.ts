/* measuring nothing */

import type { RowId } from './types';
import type { SeamTrack, SurfaceTracks } from './tracks';

export interface SpanEdge {
  rowId: RowId;
  rowAt: number;
  seam: SeamTrack;
  lastAt: number;
}

export interface SpanCorner {
  seamRow: RowId;
  seam: SeamTrack;
  boundaryRow: RowId;
  bandAt: number;
}

export function spanEdges(tracks: SurfaceTracks, ids: readonly RowId[]): SpanEdge[] {
  const edges: SpanEdge[] = [];
  tracks.rows.forEach((row, rowAt) => {
    for (const seam of row.seams) {
      const left = row.cells[seam.afterVisual];
      const right = row.cells[seam.afterVisual + 1];
      const reach = Math.max(left?.span ?? 1, right?.span ?? 1);
      const id = ids[rowAt];
      if (reach < 2 || !id) continue;
      edges.push({ rowId: id, rowAt, seam, lastAt: Math.min(rowAt + reach - 1, tracks.rows.length - 1) });
    }
  });
  return edges.filter((edge) => edge.lastAt > edge.rowAt);
}

export function edgeBox(tracks: SurfaceTracks, edge: SpanEdge): { top: number; height: number } {
  const home = tracks.rows[edge.rowAt];
  const last = tracks.rows[edge.lastAt];
  if (!home || !last) return { top: 0, height: 0 };
  const top = home.top + home.height;
  return { top, height: Math.max(0, last.top + last.height - top) };
}

export function spanCorners(tracks: SurfaceTracks, ids: readonly RowId[], edges: readonly SpanEdge[]): SpanCorner[] {
  const corners: SpanCorner[] = [];
  const near = (bandAt: number, x: number): boolean =>
    (tracks.rows[bandAt]?.seams ?? []).some((own) => Math.abs(own.x - x) < 1);
  for (const edge of edges) {
    const above = edge.rowAt - 1;
    const aboveId = ids[above];
    if (aboveId && !near(above, edge.seam.x)) {
      corners.push({ seamRow: edge.rowId, seam: edge.seam, boundaryRow: aboveId, bandAt: above });
    }
    const lastId = ids[edge.lastAt];
    if (lastId && edge.lastAt < ids.length - 1 && !near(edge.lastAt, edge.seam.x)) {
      corners.push({ seamRow: edge.rowId, seam: edge.seam, boundaryRow: lastId, bandAt: edge.lastAt });
    }
  }
  return corners;
}
