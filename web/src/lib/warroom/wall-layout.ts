import type { Tile, TileGroup } from './warroom-model';

export const TILE_ASPECT = 1.5;
export const MIN_TILE = { w: 220, h: 140 } as const;
export const PEEK_WIDTH_DEFAULT = 1150;
export const PEEK_WIDTH_MAX = 2300;
export const PEEK_REF_COLS = 3;

export function referenceTileWidth(wallWidth: number): number {
  return Math.max(0, wallWidth) / PEEK_REF_COLS;
}

export function peekWidth(wallWidth: number, stored: number): number {
  return (Number.isFinite(stored) && stored > 0 ? stored / 1000 : 0) * referenceTileWidth(wallWidth);
}

export interface PeekRange {
  ref: number;
  low: number;
  high: number;
}

export function peekRange(wall: { width: number; height: number }, tile: { width: number; height: number }): PeekRange {
  const ref = referenceTileWidth(wall.width);
  const fits = tile.height > 0 ? Math.min(wall.width, (wall.height * tile.width) / tile.height) : 0;
  return { ref, low: tile.width, high: Math.min((2 * PEEK_WIDTH_DEFAULT * ref) / 1000, fits) };
}

export function peekPosition(stored: number, range: PeekRange): number {
  if (!(stored > 0) || !(range.high > range.low)) return 0;
  const at = Math.round((100 * ((stored / 1000) * range.ref - range.low)) / (range.high - range.low));
  return Math.min(100, Math.max(0, at));
}

export function peekStored(position: number, range: PeekRange): number {
  if (!(position > 0) || !(range.high > range.low) || !(range.ref > 0)) return 0;
  const p = Math.min(100, position);
  return Math.round((1000 * (range.low + ((range.high - range.low) * p) / 100)) / range.ref);
}

export function peekScale(tile: { width: number; height: number }, wall: { width: number; height: number }, wanted: number): number {
  if (!(tile.width > 0) || !(tile.height > 0)) return 1;
  return Math.max(1, Math.min(wanted / tile.width, wall.width / tile.width, wall.height / tile.height));
}
const EMPTY_WEIGHT = 0.35;

export interface GridDims {
  cols: number;
  rows: number;
  cellW: number;
  cellH: number;
  scroll: boolean;
}

export function gridDims(count: number, width: number, height: number): GridDims {
  const n = Math.max(1, Math.floor(count));
  const w = Math.max(1, width);
  const h = Math.max(1, height);
  let best: GridDims | null = null;
  let bestScore = Infinity;
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const cellW = w / cols;
    const cellH = h / rows;
    if (cellW < MIN_TILE.w || cellH < MIN_TILE.h) continue;
    const score = Math.abs(Math.log(cellW / cellH / TILE_ASPECT)) + (EMPTY_WEIGHT * (cols * rows - n)) / n;
    if (score < bestScore - 1e-9) {
      bestScore = score;
      best = { cols, rows, cellW, cellH, scroll: false };
    }
  }
  if (best) return best;
  const cols = Math.min(n, Math.max(1, Math.floor(w / MIN_TILE.w)));
  const cellW = w / cols;
  return { cols, rows: Math.ceil(n / cols), cellW, cellH: Math.max(MIN_TILE.h, cellW / TILE_ASPECT), scroll: true };
}

export interface WallCell {
  tile: Tile;
  group: string;
  label: string;
  color: string | null;
  first: boolean;
}

export function wallCells(groups: readonly TileGroup[]): WallCell[] {
  return groups.flatMap((g) => g.tiles.map((tile, at) => ({ tile, group: g.key, label: g.label, color: g.color, first: at === 0 })));
}

export interface Edges {
  top: boolean;
  right: boolean;
  bottom: boolean;
  left: boolean;
}

export function outlineEdges(groups: readonly string[], cols: number): Edges[] {
  const at = (index: number, col: number): string | null => (col < 0 || col >= cols || index < 0 || index >= groups.length ? null : groups[index] ?? null);
  return groups.map((group, i) => {
    const col = i % cols;
    return {
      top: at(i - cols, col) !== group,
      bottom: at(i + cols, col) !== group,
      left: at(i - 1, col - 1) !== group,
      right: at(i + 1, col + 1) !== group,
    };
  });
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function peekTransform(tile: Box, bounds: Box, wanted: number): { scale: number; dx: number; dy: number } {
  const scale = Math.max(1, Math.min(wanted, bounds.width / tile.width, bounds.height / tile.height));
  const w = tile.width * scale;
  const h = tile.height * scale;
  const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const left = clamp(tile.left + tile.width / 2 - w / 2, bounds.left, bounds.left + bounds.width - w);
  const top = clamp(tile.top + tile.height / 2 - h / 2, bounds.top, bounds.top + bounds.height - h);
  return { scale, dx: left - tile.left, dy: top - tile.top };
}

export const PEEK_PAD = 6;

export const PEEK_DELAY_MS = 250;
export const PEEK_TEXT_MIN = 0.6;
export const PEEK_TEXT_MAX = 1.6;
export const PEEK_MIN_COLS = 40;

export interface PeekInput {
  cols: number;
  rows: number;
  usedCols: number;
  usedRows: number;
  cellW: number;
  cellH: number;
  boxW: number;
  boxH: number;
  peek: number;
  rest?: boolean;
}

export interface PeekCrop {
  scale: number;
  col0: number;
  row0: number;
  cols: number;
  rows: number;
  x0: number;
  y0: number;
}

export function peekCrop(p: PeekInput): PeekCrop {
  const sizes = [p.cols, p.rows, p.cellW, p.cellH, p.boxW, p.boxH];
  const whole: PeekCrop = { scale: 1, col0: 0, row0: 0, cols: Math.max(0, p.cols || 0), rows: Math.max(0, p.rows || 0), x0: 0, y0: 0 };
  if (!sizes.every((n) => Number.isFinite(n) && n > 0)) return whole;
  const peek = Number.isFinite(p.peek) && p.peek >= 1 ? p.peek : 1;
  const clamp = (v: number, lo: number, hi: number): number => Math.min(Math.max(v, lo), Math.max(lo, hi));
  const usedCols = Number.isFinite(p.usedCols) ? p.usedCols : 0;
  const usedRows = Number.isFinite(p.usedRows) ? p.usedRows : 0;
  const innerW = Math.max(1, p.boxW - 2 * PEEK_PAD);
  const innerH = Math.max(1, p.boxH - 2 * PEEK_PAD);
  const fitCols = clamp(usedCols, Math.min(p.cols, PEEK_MIN_COLS), p.cols);
  const fitW = innerW / (fitCols * p.cellW);
  const cover = Math.max(innerW / (p.cols * p.cellW), innerH / (p.rows * p.cellH));
  const scale = p.rest ? innerW / (p.cols * p.cellW) : Math.max(cover, clamp(fitW, PEEK_TEXT_MIN / peek, PEEK_TEXT_MAX / peek));
  const cols = innerW / (scale * p.cellW);
  const rows = clamp(Math.floor(innerH / (scale * p.cellH)), 1, p.rows);
  const row0 = clamp(Math.max(usedRows, rows) - rows, 0, p.rows - rows);
  return { scale, col0: 0, row0, cols, rows, x0: PEEK_PAD, y0: p.boxH - PEEK_PAD - rows * p.cellH * scale };
}
