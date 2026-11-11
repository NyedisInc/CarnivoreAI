import type { Rect } from '../../../lib/motion-grid';
import { repairSpans } from '../spans';
import type { Layout, Reservation, RowId, RowModel, Slot, SlotId } from '../types';

const SAME = 1;

function startAt(starts: readonly number[], y: number, tol: number): number {
  let best = -1;
  for (let at = 0; at < starts.length; at += 1) {
    if (Math.abs(starts[at]! - y) <= tol && (best < 0 || Math.abs(starts[at]! - y) < Math.abs(starts[best]! - y))) best = at;
  }
  return best;
}

export function layoutFromRects(base: Layout, rects: ReadonlyMap<SlotId, Rect>, gutter: number, rowTops: readonly number[] = []): Layout | null {
  const cells = base.rows.flatMap((row) => row.slots.map((slot) => ({ id: slot.id, rect: rects.get(slot.id) }))).filter((one): one is { id: SlotId; rect: Rect } => !!one.rect);
  if (cells.length === 0 || cells.length !== base.rows.reduce((sum, row) => sum + row.slots.length, 0)) return null;
  const bottomMost = Math.max(...cells.map((one) => one.rect.y + one.rect.h));
  const raw = cells.flatMap((one) => [one.rect.y, one.rect.y + one.rect.h + gutter]).filter((y) => y < bottomMost - SAME).sort((a, b) => a - b);
  const tol = Math.max(SAME, gutter);
  const clusters: number[][] = [];
  for (const y of raw) {
    const last = clusters[clusters.length - 1];
    if (last && y - last[0]! <= tol) last.push(y);
    else clusters.push([y]);
  }
  const starts = clusters.map((group) => group.find((y) => rowTops.some((top) => Math.abs(top - y) <= SAME)) ?? group[0]!);
  if (starts.length === 0) return null;
  const heights = starts.map((start, at) => (at < starts.length - 1 ? starts[at + 1]! - gutter : bottomMost) - start);
  const total = heights.reduce((sum, h) => sum + Math.max(1, h), 0);
  const used = new Set<string>(base.rows.map((row) => row.id));
  const taken = new Set<string>();
  let next = 1 + Math.max(0, ...base.rows.map((row) => Number(row.id.slice(1)) || 0));
  const kind = base.rows[0]?.kind ?? 'flex';
  const placed = cells.map((one) => {
    const first = startAt(starts, one.rect.y, tol);
    const below = startAt(starts, one.rect.y + one.rect.h + gutter, tol);
    const last = Math.max(first, below >= 0 ? below - 1 : starts.length - 1);
    return { ...one, first, last };
  });
  if (placed.some((one) => one.first < 0)) return null;
  const rows: RowModel[] = starts.map((start, at) => {
    const old = rowTops.findIndex((top) => Math.abs(top - start) <= SAME);
    const oldId = old >= 0 ? base.rows[old]?.id : undefined;
    let id: RowId;
    if (oldId && !taken.has(oldId)) id = oldId;
    else {
      while (used.has(`r${next}`)) next += 1;
      id = `r${next}` as RowId;
      used.add(id);
    }
    taken.add(id);
    const homes = placed.filter((one) => one.first === at).sort((a, b) => a.rect.x - b.rect.x);
    const pins: { of: SlotId; x: number }[] = placed
      .filter((one) => one.first < at && one.last >= at)
      .sort((a, b) => a.rect.x - b.rect.x)
      .map((one) => ({ of: one.id, x: one.rect.x }));
    const pocket = (x: number): number => pins.filter((pin) => pin.x < x).length;
    const sums = new Map<number, number>();
    for (const one of homes) sums.set(pocket(one.rect.x), (sums.get(pocket(one.rect.x)) ?? 0) + Math.max(1, one.rect.w));
    const slots: Slot[] = homes.map((one) => {
      const span = one.last - one.first + 1;
      const fr = Math.max(1, one.rect.w) / (sums.get(pocket(one.rect.x)) ?? 1);
      return span >= 2 ? { id: one.id, fr, span } : { id: one.id, fr };
    });
    const reserved: Reservation[] = pins.map((pin) => ({ of: pin.of, at: homes.filter((one) => one.rect.x < pin.x).length }));
    const row: RowModel = { id, kind, size: kind === 'flex' ? Math.max(1, heights[at]!) / total : Math.max(1, heights[at]!), slots };
    return reserved.length ? { ...row, reserved } : row;
  });
  return repairSpans({ ...base, rows });
}
