
import { PEEK_PAD } from './wall-layout';

interface Cell {
  getChars(): string;
  getWidth(): number;
  getFgColor(): number;
  getBgColor(): number;
  isFgRGB(): number;
  isBgRGB(): number;
  isFgPalette(): number;
  isBgPalette(): number;
  isBold(): number;
  isDim(): number;
  isItalic(): number;
  isUnderline(): number;
  isInverse(): number;
}

interface Line {
  getCell(x: number, cell?: Cell): Cell | undefined;
}

export interface PaintableTerm {
  cols: number;
  rows: number;
  buffer: { active: { getLine(y: number): Line | undefined; getNullCell(): Cell } };
}

export type TileTheme = Record<string, string> | undefined;

export interface CellMetrics {
  w: number;
  h: number;
}

export interface PaintGeometry {
  cell: CellMetrics;
  scale: number;
  dpr: number;
  face: string;
  fontSize: number;
  view?: { col0: number; row0: number; cols: number; rows: number; x0: number; y0: number };
}

const ANSI_KEYS = [
  'black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white',
  'brightBlack', 'brightRed', 'brightGreen', 'brightYellow', 'brightBlue', 'brightMagenta', 'brightCyan', 'brightWhite',
];
const ANSI_FALLBACK = [
  '#000000', '#cd3131', '#0dbc79', '#e5e510', '#2472c8', '#bc3fbc', '#11a8cd', '#e5e5e5',
  '#666666', '#f14c4c', '#23d18b', '#f5f543', '#3b8eea', '#d670d6', '#29b8db', '#ffffff',
];
const CUBE = [0, 95, 135, 175, 215, 255];

export function paletteColor(index: number, theme: TileTheme): string {
  if (index < 16) return theme?.[ANSI_KEYS[index] ?? ''] ?? ANSI_FALLBACK[index] ?? '#cccccc';
  if (index < 232) {
    const n = index - 16;
    return `rgb(${CUBE[Math.floor(n / 36)]},${CUBE[Math.floor(n / 6) % 6]},${CUBE[n % 6]})`;
  }
  const level = 8 + (index - 232) * 10;
  return `rgb(${level},${level},${level})`;
}

function cellColor(cell: Cell, foreground: boolean, theme: TileTheme): string | null {
  const rgb = foreground ? cell.isFgRGB() : cell.isBgRGB();
  const palette = foreground ? cell.isFgPalette() : cell.isBgPalette();
  const value = foreground ? cell.getFgColor() : cell.getBgColor();
  if (rgb) return `rgb(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255})`;
  if (palette) return paletteColor(value, theme);
  return foreground ? theme?.foreground ?? '#cccccc' : null;
}

export function measureCell(ctx: CanvasRenderingContext2D, face: string, fontSize: number): CellMetrics {
  ctx.font = `${fontSize}px ${face || 'monospace'}`;
  return { w: ctx.measureText('W').width || fontSize * 0.6, h: Math.ceil(fontSize * 1.2) };
}

export function contentExtent(buffer: PaintableTerm['buffer']['active'], cols: number, rows: number): { usedCols: number; usedRows: number } {
  const scratch = buffer.getNullCell();
  let usedRows = 0;
  let usedCols = 0;
  for (let y = rows - 1; y >= 0; y -= 1) {
    const line = buffer.getLine(y);
    if (!line) continue;
    for (let x = cols - 1; x >= 0; x -= 1) {
      const c = line.getCell(x, scratch);
      if (!c) continue;
      const chars = c.getChars();
      if ((chars !== '' && chars !== ' ') || !cellBgDefault(c)) {
        if (usedRows === 0) usedRows = y + 1;
        usedCols = Math.max(usedCols, x + 1);
        break;
      }
    }
  }
  return { usedCols, usedRows };
}

function cellBgDefault(c: Cell): boolean {
  return !c.isBgRGB() && !c.isBgPalette();
}

interface Run {
  x: number;
  text: string;
  fg: string;
  bg: string | null;
  font: string;
  dim: boolean;
  underline: boolean;
}

function drawRun(ctx: CanvasRenderingContext2D, run: Run, y: number, cell: CellMetrics, cells: number): void {
  if (run.bg) {
    ctx.fillStyle = run.bg;
    ctx.fillRect(run.x * cell.w, y * cell.h, cells * cell.w, cell.h);
  }
  if (run.text.trim() === '' && !run.underline) return;
  ctx.globalAlpha = run.dim ? 0.55 : 1;
  ctx.fillStyle = run.fg;
  ctx.font = run.font;
  ctx.fillText(run.text, run.x * cell.w, y * cell.h + cell.h * 0.8);
  if (run.underline) ctx.fillRect(run.x * cell.w, (y + 1) * cell.h - 2, cells * cell.w, 1);
  ctx.globalAlpha = 1;
}

export function paintTile(canvas: HTMLCanvasElement, term: PaintableTerm, theme: TileTheme, geo: PaintGeometry): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const { cell, fontSize, face } = geo;
  const k = geo.scale * geo.dpr;
  const view = geo.view;
  ctx.setTransform(k, 0, 0, k, 0, 0);
  ctx.clearRect(0, 0, canvas.width / k, canvas.height / k);
  ctx.textBaseline = 'alphabetic';
  const base = theme?.background;
  if (view) {
    if (base) {
      ctx.fillStyle = base;
      ctx.fillRect(0, 0, canvas.width / k, canvas.height / k);
    }
    ctx.save();
    ctx.setTransform(geo.dpr, 0, 0, geo.dpr, 0, 0);
    ctx.beginPath();
    ctx.rect(PEEK_PAD, PEEK_PAD, canvas.width / geo.dpr - 2 * PEEK_PAD, canvas.height / geo.dpr - 2 * PEEK_PAD);
    ctx.clip();
    ctx.setTransform(k, 0, 0, k, (view.x0 - view.col0 * cell.w * geo.scale) * geo.dpr, (view.y0 - view.row0 * cell.h * geo.scale) * geo.dpr);
  } else if (base) {
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, term.cols * cell.w, term.rows * cell.h);
  }
  const rowFrom = view ? Math.max(0, Math.floor(view.row0)) : 0;
  const rowTo = view ? Math.min(term.rows, Math.ceil(view.row0 + view.rows)) : term.rows;
  const colTo = view ? Math.min(term.cols, Math.ceil(view.col0 + view.cols)) : term.cols;
  const buffer = term.buffer.active;
  const scratch = buffer.getNullCell();
  const defaultFg = theme?.foreground ?? '#cccccc';
  for (let y = rowFrom; y < rowTo; y += 1) {
    const line = buffer.getLine(y);
    if (!line) continue;
    let run: Run | null = null;
    let runCells = 0;
    const flush = (): void => {
      if (run) drawRun(ctx, run, y, cell, runCells);
      run = null;
      runCells = 0;
    };
    for (let x = 0; x < colTo; x += 1) {
      const c = line.getCell(x, scratch);
      if (!c) break;
      const width = c.getWidth();
      if (width === 0) continue;
      const chars = c.getChars() || ' ';
      let fg = cellColor(c, true, theme) ?? defaultFg;
      let bg = cellColor(c, false, theme);
      if (c.isInverse()) {
        const swapped = bg ?? theme?.background ?? '#000000';
        bg = fg;
        fg = swapped;
      }
      const font = `${c.isItalic() ? 'italic ' : ''}${c.isBold() ? 'bold ' : ''}${fontSize}px ${face || 'monospace'}`;
      const dim = !!c.isDim();
      const underline = !!c.isUnderline();
      const plain = width === 1 && chars.charCodeAt(0) < 128 && chars.length === 1;
      const same = run !== null && plain && run.fg === fg && run.bg === bg && run.font === font && run.dim === dim
        && run.underline === underline && run.x + runCells === x && run.text.length === runCells;
      if (same && run) {
        run.text += chars;
        runCells += 1;
        continue;
      }
      flush();
      run = { x, text: chars, fg, bg, font, dim, underline };
      runCells = width;
      if (!plain) flush();
    }
    flush();
  }
  if (view) ctx.restore();
}
