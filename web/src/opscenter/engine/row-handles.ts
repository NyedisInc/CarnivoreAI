
import type { SurfaceTracks } from './tracks';

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
