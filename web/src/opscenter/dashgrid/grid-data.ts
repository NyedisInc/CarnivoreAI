/* the widget menu */
import { firstFit, pack, type PackItem } from '../../lib/motion-grid/pack';
import type { MetaMap, RowModel, SlotId } from '../engine/types';
import { META } from '../engine/meta';
import { convertV6 } from './format/convert-v6';
import { GRID_COLS, GRID_PITCH, validateGrid, writeBoardGrid, type BoardBlob, type BoardGrid, type GridItem } from './format/grid-format';
import { rowsSig } from './format/rows-sig';

export type Cols = 24 | 12 | 1;

export type OrderedGrid = BoardGrid & { order?: string[] };

export function membershipOf(rows: readonly RowModel[]): SlotId[] {
  return rows.flatMap((r) => r.slots.map((s) => s.id));
}

function same(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function converted(rows: RowModel[], metas: MetaMap): OrderedGrid {
  return { v: 1, cols: GRID_COLS, pitch: GRID_PITCH, layouts: { '24': convertV6({ rows }, metas) }, rowsSig: rowsSig(rows), order: membershipOf(rows) };
}

function reconcileLayout(items: readonly GridItem[], ids: readonly SlotId[], sizes: ReadonlyMap<string, GridItem>, cols: number): GridItem[] {
  const want = new Set(ids);
  const kept: GridItem[] = items.filter((i) => want.has(i.id));
  for (const id of ids) {
    if (kept.some((i) => i.id === id)) continue;
    const size = sizes.get(id);
    const w = Math.min(cols, size?.w ?? 8);
    const h = size?.h ?? 6;
    kept.push({ id, ...firstFit(kept, cols, w, h), w, h });
  }
  return pack(kept, cols, null) as GridItem[];
}

export function resolveGrid(blob: { grid?: unknown; rows: RowModel[] }, rows: RowModel[] = blob.rows, metas: MetaMap = META): OrderedGrid {
  const ids = membershipOf(rows);
  const grid = blob.grid;
  if (!validateGrid(grid)) return converted(rows, metas);
  const have = grid.layouts['24'].map((i) => i.id);
  if (grid.rowsSig === rowsSig(rows) && have.length === ids.length && ids.every((id) => have.includes(id))) return grid as OrderedGrid;
  const order = (grid as OrderedGrid).order;
  const survivors = new Set<string>(have.filter((id) => ids.includes(id)));
  const rearranged = !order || !same(order.filter((id) => survivors.has(id)), ids.filter((id) => survivors.has(id)));
  if (rearranged) return converted(rows, metas);
  const sizes = new Map<string, GridItem>(convertV6({ rows }, metas).map((i) => [i.id, i]));
  const layouts: BoardGrid['layouts'] = { '24': reconcileLayout(grid.layouts['24'], ids, sizes, 24) };
  for (const c of ['12', '1'] as const) {
    const stored = grid.layouts[c];
    if (stored) layouts[c] = reconcileLayout(stored, ids, sizes, Number(c));
  }
  return { ...grid, layouts, rowsSig: rowsSig(rows), order: ids };
}

export function layoutFor(grid: BoardGrid, cols: Cols): GridItem[] {
  const stored = grid.layouts[String(cols) as '24' | '12' | '1'];
  if (stored) return stored;
  const base = grid.layouts['24'];
  if (cols === 24) return base;
  if (cols === 12) return pack(base.map((i) => ({ ...i, x: Math.floor(i.x / 2), w: Math.max(1, Math.ceil(i.w / 2)) })), 12, null) as GridItem[];
  const sorted = [...base].sort((a, b) => a.y - b.y || a.x - b.x);
  return pack(sorted.map((i) => ({ ...i, x: 0, w: 1 })), 1, null) as GridItem[];
}

export function withLayout(grid: OrderedGrid, cols: Cols, items: readonly PackItem[]): OrderedGrid {
  const next = items.map((i) => ({ id: i.id as SlotId, x: i.x, y: i.y, w: i.w, h: i.h }));
  const layouts: BoardGrid['layouts'] = cols === 24 ? { '24': next } : { ...grid.layouts, [String(cols)]: next };
  return { ...grid, layouts };
}

export function blobWithGrid<T extends { rows: RowModel[]; grid?: unknown }>(blob: T, grid: OrderedGrid, metas: MetaMap = META): T & { grid: OrderedGrid } {
  const ids = membershipOf(blob.rows);
  const ready = resolveGrid({ rows: blob.rows, grid }, blob.rows, metas);
  const out = writeBoardGrid(blob as unknown as BoardBlob, ready, ids, metas);
  return { ...(blob as T), rows: out.rows, grid: { ...(out.grid as OrderedGrid), order: ids } };
}
