
export const TERMINAL_MIN_COLUMNS = 60;

/* the bottom bar */
export const TERMINAL_MIN_ROWS = 5;

export const CELL_WIDTH_FALLBACK_PX = 8.4;

export const CELL_HEIGHT_FALLBACK_PX = 17;

export const BAR_GRAB_MIN_PX = 44;

import { wrap } from '../terminal-provider/provider';

export interface MetricsWindow {
  TerminalController?: { term?: object };
}

export function terminalCell(win: MetricsWindow = typeof window === 'undefined' ? {} : (window as MetricsWindow)): { width: number; height: number } {
  const cell = wrap(win.TerminalController?.term).cellSize();
  const width = cell?.width;
  const height = cell?.height;
  return {
    width: typeof width === 'number' && Number.isFinite(width) && width > 0 ? width : CELL_WIDTH_FALLBACK_PX,
    height: typeof height === 'number' && Number.isFinite(height) && height > 0 ? height : CELL_HEIGHT_FALLBACK_PX,
  };
}

export function maxBarPx(room: number, axis: 'x' | 'y', cell: { width: number; height: number } = terminalCell(), min: number = BAR_GRAB_MIN_PX): number {
  const floor = axis === 'x' ? TERMINAL_MIN_COLUMNS * cell.width : TERMINAL_MIN_ROWS * cell.height;
  return Math.max(min, Math.floor(room - floor));
}

export function clampBar(px: number, room: number, axis: 'x' | 'y', cell?: { width: number; height: number }, min: number = BAR_GRAB_MIN_PX): number {
  return Math.min(maxBarPx(room, axis, cell, min), Math.max(min, Math.round(px)));
}
