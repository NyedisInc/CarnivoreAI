import { describe, expect, it } from 'vitest';
import { contentExtent, paintTile, paletteColor, type PaintableTerm } from './tile-canvas';

function cell(ch: string, over: Record<string, number> = {}) {
  return {
    getChars: () => ch,
    getWidth: () => 1,
    getFgColor: () => over.fg ?? 0,
    getBgColor: () => over.bg ?? 0,
    isFgRGB: () => 0,
    isBgRGB: () => 0,
    isFgPalette: () => over.fgPal ?? 0,
    isBgPalette: () => over.bgPal ?? 0,
    isBold: () => 0,
    isDim: () => 0,
    isItalic: () => 0,
    isUnderline: () => 0,
    isInverse: () => over.inverse ?? 0,
  };
}

function fakeCanvas() {
  const calls: Array<[string, ...unknown[]]> = [];
  const ctx = new Proxy({} as Record<string, unknown>, {
    get: (_t, name: string) => (...args: unknown[]) => void calls.push([name, ...args]),
    set: () => true,
  });
  return { calls, canvas: { width: 100, height: 40, getContext: () => ctx } as unknown as HTMLCanvasElement };
}

describe('war room tile canvas', () => {
  it('maps the 256 palette: theme ansi, color cube, gray ramp', () => {
    expect(paletteColor(1, { red: '#f00' })).toBe('#f00');
    expect(paletteColor(16, undefined)).toBe('rgb(0,0,0)');
    expect(paletteColor(231, undefined)).toBe('rgb(255,255,255)');
    expect(paletteColor(232, undefined)).toBe('rgb(8,8,8)');
  });

  it('draws a run of equal ASCII cells as ONE fillText and skips blank cells', () => {
    const row = [cell('h', { fg: 2, fgPal: 1 }), cell('i', { fg: 2, fgPal: 1 }), cell(' ')];
    const term: PaintableTerm = {
      cols: 3,
      rows: 1,
      buffer: { active: { getNullCell: () => cell(''), getLine: () => ({ getCell: (x: number) => row[x] }) } },
    };
    const { calls, canvas } = fakeCanvas();
    paintTile(canvas, term, { green: '#0f0', background: '#000' }, { cell: { w: 8, h: 16 }, scale: 1, dpr: 1, face: 'monospace', fontSize: 14 });
    const text = calls.filter((c) => c[0] === 'fillText');
    expect(text.map((c) => c[1])).toEqual(['hi']);
  });

  it('measures the content extent: trailing blank rows are skipped, a background-only cell counts, columns are cells', () => {
    const rows: Array<Array<ReturnType<typeof cell>>> = [
      [cell('a'), cell(' '), cell(' '), cell(' '), cell(' ')],
      [cell(' '), cell(' '), cell(' '), cell(' ', { bgPal: 1, bg: 4 }), cell(' ')],
      [cell(' '), cell(' '), cell(' '), cell(' '), cell(' ')],
    ];
    const buffer = { getNullCell: () => cell(''), getLine: (y: number) => ({ getCell: (x: number) => rows[y]?.[x] }) };
    expect(contentExtent(buffer, 5, 3)).toEqual({ usedCols: 4, usedRows: 2 });
    const blank = { getNullCell: () => cell(''), getLine: () => ({ getCell: () => cell(' ') }) };
    expect(contentExtent(blank, 5, 3)).toEqual({ usedCols: 0, usedRows: 0 });
  });

  it('with a view it paints only the visible rows, shifted to the crop corner', () => {
    const rows = [0, 1, 2, 3].map((n) => [cell(String(n))]);
    const term: PaintableTerm = {
      cols: 1,
      rows: 4,
      buffer: { active: { getNullCell: () => cell(''), getLine: (y: number) => ({ getCell: (x: number) => rows[y]?.[x] }) } },
    };
    const { calls, canvas } = fakeCanvas();
    paintTile(canvas, term, { background: '#000' }, {
      cell: { w: 8, h: 16 }, scale: 1, dpr: 1, face: 'monospace', fontSize: 14, view: { col0: 0, row0: 1.5, cols: 1, rows: 2, x0: 5, y0: 7 },
    });
    expect(calls.filter((c) => c[0] === 'fillText').map((c) => c[1])).toEqual(['1', '2', '3']);
    expect(calls.filter((c) => c[0] === 'setTransform').pop()).toEqual(['setTransform', 1, 0, 0, 1, 5, -17]);
  });
});
