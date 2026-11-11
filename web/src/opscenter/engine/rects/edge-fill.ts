import type { Rect } from '../../../lib/motion-grid';
import type { SlotId } from '../types';
import type { DividerSpec } from './dividers';

const NEAR = 1.5;
const SQUARE = 14;

const columnsOf = (specs: readonly DividerSpec[]): DividerSpec[] => specs.filter((one) => one.kind === 'col' && one.seam);

export function extraSpecs(specs: readonly DividerSpec[], rects: ReadonlyMap<SlotId, Rect>, box: { width: number; height: number }, gutter: number): DividerSpec[] {
  const out: DividerSpec[] = [];
  const cols = columnsOf(specs);
  const cells = [...rects.values()];
  const shared = { flexSpace: 0, rowFree: 0, free: 0 };
  for (const [id, r] of rects) {
    for (const side of ['w', 'e'] as const) {
      const line = side === 'w' ? r.x - gutter : r.x + r.w;
      if (line < 0 || line + gutter > box.width + 0.5) continue;
      const across = cells.filter((o) => Math.abs((side === 'w' ? o.x + o.w : o.x - gutter) - line) <= NEAR && o.y < r.y + r.h && o.y + o.h > r.y);
      if (across.length === 0) continue;
      const covered = cols.filter((c) => Math.abs(c.rect.x - line) <= NEAR).map((c) => [c.rect.y, c.rect.y + c.rect.h] as const);
      let from = r.y;
      const need: [number, number][] = [];
      for (const [a, b] of [...covered].sort((p, q) => p[0] - q[0])) {
        if (a > from + NEAR) need.push([from, Math.min(a, r.y + r.h)]);
        from = Math.max(from, b);
      }
      if (from < r.y + r.h - NEAR) need.push([from, r.y + r.h]);
      for (const [y0, y1] of need) {
        if (y1 - y0 < NEAR) continue;
        const gov = cols.filter((c) => Math.abs(c.rect.x - line) <= NEAR).sort((p, q) => Math.abs(p.rect.y - y0) - Math.abs(q.rect.y - y0))[0];
        if (!gov) continue;
        out.push({ ...gov, id: `side:${id}:${side}:${Math.round(y0)}`, rect: { x: gov.rect.x, y: Math.round(y0), w: gutter, h: Math.round(y1 - y0) }, mirror: true });
      }
    }
  }
  const verticals = [...cols, ...out];
  const squares = specs.filter((one) => one.kind === 'inter' || one.kind === 'corner');
  for (const row of specs.filter((one) => one.kind === 'row' && one.seg)) {
    for (const end of [row.rect.x - gutter, row.rect.x + row.rect.w] as const) {
      const cy = row.rect.y + gutter / 2;
      const col = verticals.find((c) => Math.abs(c.rect.x - end) <= NEAR && cy >= c.rect.y - NEAR && cy <= c.rect.y + c.rect.h + NEAR);
      if (!col?.seam) continue;
      const cx = col.rect.x + gutter / 2;
      if (squares.some((q) => cx >= q.rect.x - NEAR && cx <= q.rect.x + q.rect.w + NEAR && cy >= q.rect.y - NEAR && cy <= q.rect.y + q.rect.h + NEAR)) continue;
      const id = `cor:${col.id}:${row.id}`;
      if (out.some((one) => one.id === id)) continue;
      out.push({
        ...shared,
        flexSpace: row.flexSpace,
        free: col.free,
        rowFree: col.rowFree,
        mirror: false,
        id,
        kind: 'corner',
        rect: { x: Math.round(cx - SQUARE / 2), y: Math.round(cy - SQUARE / 2), w: SQUARE, h: SQUARE },
        rowId: col.rowId,
        seam: col.seam,
        boundary: row.rowId,
        seg: row.seg,
        ...(row.fit ? { fit: row.fit } : {}),
        ...(end > row.rect.x ? { diag: 'nesw' as const } : {}),
      });
    }
  }
  return out;
}
