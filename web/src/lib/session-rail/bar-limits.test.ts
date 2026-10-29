import { describe, expect, test } from 'vitest';
import { BAR_GRAB_MIN_PX, CELL_WIDTH_FALLBACK_PX, TERMINAL_MIN_COLUMNS, clampBar, maxBarPx, terminalCell } from './bar-limits';
import { barThickness } from '../widget-bars/bar-size';

const cell = { width: 10, height: 20 };

describe('bar limits', () => {
  test('the column floor comes from the real cell width', () => {
    expect(maxBarPx(1000, 'x', cell)).toBe(1000 - TERMINAL_MIN_COLUMNS * 10);
    expect(maxBarPx(2000, 'x', { width: 12, height: 20 })).toBe(2000 - TERMINAL_MIN_COLUMNS * 12);
  });

  test('the metrics are read from xterm when present and estimated when not', () => {
    const win = { TerminalController: { term: { _core: { _renderService: { dimensions: { css: { cell: { width: 9.5, height: 18 } } } } } } } };
    expect(terminalCell(win)).toEqual({ width: 9.5, height: 18 });
    expect(terminalCell({}).width).toBe(CELL_WIDTH_FALLBACK_PX);
    expect(terminalCell({ TerminalController: { term: { _core: { _renderService: { dimensions: { css: { cell: { width: 0 } } } } } } } }).width).toBe(CELL_WIDTH_FALLBACK_PX);
  });

  test('a bar always keeps the grab minimum, even in a window too narrow for 60 columns', () => {
    expect(maxBarPx(300, 'x', cell)).toBe(BAR_GRAB_MIN_PX);
    expect(clampBar(1, 300, 'x', cell)).toBe(BAR_GRAB_MIN_PX);
    expect(clampBar(0, 1000, 'y', cell)).toBe(BAR_GRAB_MIN_PX);
  });

  test('a floor of its own (the bottom strip) replaces the grab minimum', () => {
    const strip = barThickness('bottom', 'cozy');
    expect(strip).toBe(36);
    expect(clampBar(0, 1000, 'y', cell, strip)).toBe(36);
    expect(maxBarPx(50, 'y', cell, strip)).toBe(36);
    expect(clampBar(40, 1000, 'y', cell, strip)).toBe(40);
  });

  test('there is no fixed cap: a huge window allows a huge bar', () => {
    expect(clampBar(5000, 6000, 'x', cell)).toBe(5000);
  });
});
