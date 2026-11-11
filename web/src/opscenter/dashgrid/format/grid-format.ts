
import { META } from '../../engine/meta';
import { freeRowId, normalizeRow, rowHeightFor, withoutCell } from '../../engine/model';
import { repairSpans } from '../../engine/spans';
import type { Layout, MetaMap, RowModel, SlotId } from '../../engine/types';
import { convertV6 } from './convert-v6';
import { rowsSig } from './rows-sig';

export const GRID_COLS = 24;
export const GRID_PITCH = 40;
export const MAX_ITEMS = 200;
export const MAX_H = 60;

export interface GridItem {
  id: SlotId;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface BoardGrid {
  v: 1;
  cols: 24;
  pitch: 40;
  layouts: { '24': GridItem[]; '12'?: GridItem[]; '1'?: GridItem[] };
  rowsSig: string;
}

export type BoardBlob = Record<string, unknown> & { v: 6; rows: RowModel[]; grid?: unknown };

export interface GridRead {
  grid: BoardGrid;
  source: 'grid' | 'converted';
}

function int(v: unknown, lo: number, hi: number): v is number {
  return typeof v === 'number' && Number.isInteger(v) && v >= lo && v <= hi;
}

function validItems(items: unknown, cols: number): items is GridItem[] {
  if (!Array.isArray(items) || items.length > MAX_ITEMS) return false;
  const seen = new Set<string>();
  for (const raw of items) {
    if (!raw || typeof raw !== 'object') return false;
    const o = raw as Record<string, unknown>;
    if (typeof o['id'] !== 'string' || seen.has(o['id'])) return false;
    seen.add(o['id']);
    if (!int(o['x'], 0, cols) || !int(o['y'], 0, 1e6) || !int(o['w'], 1, cols) || !int(o['h'], 1, MAX_H)) return false;
    if ((o['x'] as number) + (o['w'] as number) > cols) return false;
  }
  return true;
}

export function validateGrid(grid: unknown): grid is BoardGrid {
  if (!grid || typeof grid !== 'object') return false;
  const g = grid as Record<string, unknown>;
  if (g['v'] !== 1 || g['cols'] !== GRID_COLS || g['pitch'] !== GRID_PITCH || typeof g['rowsSig'] !== 'string') return false;
  const layouts = g['layouts'];
  if (!layouts || typeof layouts !== 'object') return false;
  const l = layouts as Record<string, unknown>;
  if (!validItems(l['24'], 24)) return false;
  if (l['12'] !== undefined && !validItems(l['12'], 12)) return false;
  if (l['1'] !== undefined && !validItems(l['1'], 1)) return false;
  return true;
}

export function readBoardGrid(blob: BoardBlob): GridRead {
  if (validateGrid(blob.grid) && blob.grid.rowsSig === rowsSig(blob.rows)) return { grid: blob.grid, source: 'grid' };
  return { grid: { v: 1, cols: 24, pitch: 40, layouts: { '24': convertV6(blob) }, rowsSig: rowsSig(blob.rows) }, source: 'converted' };
}

/* the new widgets */
function reconcileRows(blob: BoardBlob, membership: ReadonlySet<SlotId>, metas: MetaMap): RowModel[] {
  const present = new Set<SlotId>(blob.rows.flatMap((r) => r.slots.map((s) => s.id)));
  const gone = [...present].filter((id) => !membership.has(id));
  const added = [...membership].filter((id) => !present.has(id));
  if (!gone.length && !added.length) return blob.rows;
  let rows = blob.rows.map((row) => gone.reduce((r, id) => (r.slots.some((s) => s.id === id) ? normalizeRow(withoutCell(r, id)) : r), row));
  rows = rows.filter((r) => r.slots.length > 0 || (r.reserved?.length ?? 0) > 0);
  let layout = repairSpans({ ...(blob as unknown as Layout), rows });
  for (const id of added) {
    layout = { ...layout, rows: [...layout.rows, { id: freeRowId(layout), kind: 'px', size: rowHeightFor([id], metas), slots: [{ id, fr: 1 }] }] };
  }
  return layout.rows;
}

export function writeBoardGrid(blob: BoardBlob, grid: BoardGrid, membership: readonly SlotId[], metas: MetaMap = META): BoardBlob {
  if (!validateGrid(grid)) throw new RangeError('writeBoardGrid:malformed-grid');
  const want = new Set<SlotId>(membership);
  const have = grid.layouts['24'].map((i) => i.id);
  if (have.length !== want.size || have.some((id) => !want.has(id))) throw new RangeError('writeBoardGrid:ids-differ');
  const rows = reconcileRows(blob, want, metas);
  return { ...blob, rows, grid: { ...grid, rowsSig: rowsSig(rows) } };
}
