import type { Layout } from '../engine/types';
import { pack } from '../../lib/motion-grid/pack';
import { GUTTER } from '../engine/tracks';
import { blobWithGrid, layoutFor, resolveGrid, withLayout, type Cols, type OrderedGrid } from './grid-data';
import { GRID_PITCH, MAX_H, validateGrid, type GridItem } from './format/grid-format';
import { rowsSig } from './format/rows-sig';

export const SETTLE_MS = 800;

export const MAX_LAYOUT_BYTES = 131072;

export const GRID_CACHE_KEY = 'cloudecode.opscenter.dashgrid.v1';

const dash: { board: string; grid: OrderedGrid | null } = $state({ board: 'home', grid: null });
const listeners = new Set<() => void>();
let busyFn: () => boolean = () => false;
let memo: { raw: unknown; rows: unknown; out: OrderedGrid } | null = null;

function cached(board: string): OrderedGrid | null {
  try {
    const map = JSON.parse(localStorage.getItem(GRID_CACHE_KEY) ?? '{}') as Record<string, unknown>;
    const grid = map[board];
    return validateGrid(grid) ? (grid as OrderedGrid) : null;
  } catch {
    return null;
  }
}

function cache(board: string, grid: OrderedGrid): void {
  try {
    const map = JSON.parse(localStorage.getItem(GRID_CACHE_KEY) ?? '{}') as Record<string, unknown>;
    map[board] = grid;
    localStorage.setItem(GRID_CACHE_KEY, JSON.stringify(map));
  } catch {
  }
}

function notify(): void {
  listeners.forEach((fn) => fn());
}

export function onGridChange(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setDashBusy(fn: (() => boolean) | null): void {
  busyFn = fn ?? (() => false);
}

export function dashBusy(): boolean {
  return busyFn();
}

export function loadDashGrid(board: string, blob: { grid?: unknown }): void {
  dash.board = board;
  dash.grid = validateGrid(blob.grid) ? (blob.grid as OrderedGrid) : cached(board);
}

export function dashGridFor(layout: Pick<Layout, 'rows'>): OrderedGrid {
  const raw = dash.grid ?? cached(dash.board);
  if (memo && memo.raw === raw && memo.rows === layout.rows) return memo.out;
  const out = resolveGrid({ grid: raw ?? undefined, rows: layout.rows as Layout['rows'] }, layout.rows as Layout['rows']);
  memo = { raw, rows: layout.rows, out };
  return out;
}

export function dashItems(layout: Pick<Layout, 'rows'>, cols: Cols): GridItem[] {
  return layoutFor(dashGridFor(layout), cols);
}

export function commitDashLayout(layout: Pick<Layout, 'rows'>, cols: Cols, items: readonly GridItem[]): void {
  const grid = { ...withLayout(dashGridFor(layout), cols, items), rowsSig: rowsSig(layout.rows) };
  dash.grid = grid;
  cache(dash.board, grid);
  notify();
}

export function snapshotDash(layout: Pick<Layout, 'rows'>): OrderedGrid {
  return dashGridFor(layout);
}

export function restoreDash(grid: OrderedGrid): void {
  dash.grid = grid;
  cache(dash.board, grid);
  notify();
}

export function blobForSend<T extends Layout>(layout: T): T | (T & { grid: OrderedGrid }) {
  try {
    const out = blobWithGrid(layout, dashGridFor(layout));
    const bytes = new TextEncoder().encode(JSON.stringify(out)).length;
    if (bytes <= MAX_LAYOUT_BYTES) return out;
    console.warn('[dashgrid] grid would pass the layout cap, sending rows only', { bytes, cap: MAX_LAYOUT_BYTES });
  } catch (error) {
    console.warn('[dashgrid] grid refused, sending rows only', { rows: layout.rows.length, error });
  }
  return layout;
}

export function isDashGridPage(page: string): boolean {
  return page === 'home';
}

export function growDashItem(layout: Pick<Layout, 'rows'>, cols: Cols, width: number, id: string, minPx: { w: number; h: number }): boolean {
  const items = dashItems(layout, cols);
  const item = items.find((i) => i.id === id);
  if (!item || width <= 0) return false;
  const colW = Math.max(1, (width - GUTTER * (cols - 1)) / cols);
  const w = Math.min(cols, Math.max(item.w, Math.ceil((minPx.w + GUTTER) / (colW + GUTTER))));
  const h = Math.min(MAX_H, Math.max(item.h, Math.ceil((minPx.h + GUTTER) / GRID_PITCH)));
  if (w === item.w && h === item.h) return false;
  const grown = items.map((i) => (i.id === id ? { ...i, w, h } : i));
  commitDashLayout(layout, cols, pack(grown, cols, { id, x: Math.min(item.x, cols - w), y: item.y }) as GridItem[]);
  return true;
}

export function resetDashGrid(): void {
  dash.grid = null;
  try {
    const map = JSON.parse(localStorage.getItem(GRID_CACHE_KEY) ?? '{}') as Record<string, unknown>;
    delete map[dash.board];
    localStorage.setItem(GRID_CACHE_KEY, JSON.stringify(map));
  } catch {
  }
  notify();
}
