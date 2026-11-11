
import { spanOf } from './spans';
import { GUTTER } from './tracks';
import type { RowModel } from './types';

export const NOMINAL_WIDTH = 1200;
export const NOMINAL_HEIGHT = 800;

export function mergedFlexSize(rows: readonly RowModel[], merged: readonly RowModel[], m: number, lost: number, height: number = NOMINAL_HEIGHT): number {
  const total = rows.reduce((sum, row) => (row.kind === 'flex' ? sum + row.size : sum), 0);
  const fixed = rows.reduce((sum, row) => (row.kind === 'flex' ? sum : sum + row.size), 0);
  const space = height - fixed - GUTTER * (rows.length - 1);
  if (merged.some((row) => row.kind !== 'flex') || total - m <= 1e-9 || space <= GUTTER * lost) return m;
  const px = (m / total) * space + GUTTER * lost;
  const left = space + GUTTER * lost - px;
  return left > 1e-9 ? (px * (total - m)) / left : m;
}

export function flexTotal(rows: readonly RowModel[]): number {
  return rows.reduce((sum, row) => (row.kind === 'flex' ? sum + row.size : sum), 0);
}

export function restoreFlexTotal<T extends RowModel>(rows: readonly T[], total: number): T[] {
  const now = flexTotal(rows);
  if (now <= 0 || total <= 0 || Math.abs(now - total) < 1e-12) return rows as T[];
  return rows.map((row) => (row.kind === 'flex' ? { ...row, size: (row.size * total) / now } : row));
}

export function keepTrailingRowPixels(rows: readonly RowModel[], height: number = NOMINAL_HEIGHT): RowModel[] {
  let last = rows.length - 1;
  while (last >= 0 && rows[last]!.slots.length === 0) last -= 1;
  const covering = rows.flatMap((row, at) => (at <= last ? row.slots.filter((slot) => at + spanOf(slot) > last).map((slot) => ({ at, slot })) : []));
  if (last < 0 || last === rows.length - 1 || covering.every((one) => one.at + spanOf(one.slot) >= rows.length)) return [...rows];
  const total = flexTotal(rows);
  const out = [...rows];
  for (let at = rows.length - 1; at > last; at -= 1) {
    const up = out[at - 1]!;
    const gone = out[at]!;
    if (up.kind !== 'flex' || gone.kind !== 'flex' || gone.size === 0) continue;
    out[at - 1] = { ...up, size: mergedFlexSize(out, [up, gone], up.size + gone.size, 1, height) };
    out[at] = { ...gone, size: 0 };
  }
  return restoreFlexTotal(out, total);
}
