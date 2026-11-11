
import type { SurfaceTracks } from './tracks';
import type { SlotId } from './types';

export function boundaryHandles(tracks: SurfaceTracks, at: number, width: number, gutter: number): [number, number][] {
  const above = tracks.rows[at]?.cells ?? [];
  const below = tracks.rows[at + 1]?.cells ?? [];
  const limit = Math.max(0, Math.floor(width));
  const pieces: [number, number][] = [];
  for (const top of above) {
    if (top.slotId === null && !top.reserved) continue;
    for (const under of below) {
      if (under.slotId === null) continue;
      const start = Math.max(top.x, under.x, 0);
      const end = Math.min(top.x + top.width, under.x + under.width, limit);
      if (end > start) pieces.push([start, end]);
    }
  }
  pieces.sort((a, b) => a[0] - b[0]);
  const joined: [number, number][] = [];
  for (const piece of pieces) {
    const last = joined[joined.length - 1];
    if (last && piece[0] - last[1] <= gutter) last[1] = Math.max(last[1], piece[1]);
    else joined.push([piece[0], piece[1]]);
  }
  return joined.map(([start, end]) => {
    const left = start <= gutter ? 0 : start;
    const right = limit - end <= gutter ? limit : end;
    return [left, right - left] as [number, number];
  });
}

export interface BoundarySegment {
  left: number;
  width: number;
  above: SlotId[];
  below: SlotId[];
}

export function boundarySegments(tracks: SurfaceTracks, at: number, width: number, gutter: number): BoundarySegment[] {
  const above = tracks.rows[at]?.cells ?? [];
  const below = tracks.rows[at + 1]?.cells ?? [];
  const limit = Math.max(0, Math.floor(width));
  const parent = new Map<SlotId, SlotId>();
  const find = (id: SlotId): SlotId => {
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root)!;
    parent.set(id, root);
    return root;
  };
  const pieces: { start: number; end: number; top: SlotId; under: SlotId }[] = [];
  for (const top of above) {
    const topId = top.slotId ?? top.of;
    if (!topId) continue;
    for (const under of below) {
      if (under.slotId === null) continue;
      const start = Math.max(top.x, under.x, 0);
      const end = Math.min(top.x + top.width, under.x + under.width, limit);
      if (end <= start) continue;
      for (const id of [topId, under.slotId]) if (!parent.has(id)) parent.set(id, id);
      parent.set(find(topId), find(under.slotId));
      pieces.push({ start, end, top: topId, under: under.slotId });
    }
  }
  const groups = new Map<SlotId, BoundarySegment & { end: number }>();
  for (const piece of pieces.sort((a, b) => a.start - b.start)) {
    const root = find(piece.top);
    const one = groups.get(root) ?? { left: piece.start, width: 0, end: piece.end, above: [], below: [] };
    one.left = Math.min(one.left, piece.start);
    one.end = Math.max(one.end, piece.end);
    if (!one.above.includes(piece.top)) one.above.push(piece.top);
    if (!one.below.includes(piece.under)) one.below.push(piece.under);
    groups.set(root, one);
  }
  return [...groups.values()]
    .sort((a, b) => a.left - b.left)
    .map((one) => {
      const left = one.left <= gutter ? 0 : one.left;
      const right = limit - one.end <= gutter ? limit : one.end;
      return { left, width: right - left, above: one.above, below: one.below };
    });
}
