import { describe, expect, test } from 'vitest';
import { EDGE, MIN_SHEET_HEIGHT, SHEET_GAP, sheetPlacement } from './sheet-placement';

const view = { width: 1400, height: 900 };

describe('sheetPlacement', () => {
  test('beside a widget with room below, the sheet starts level with it', () => {
    const place = sheetPlacement({ left: 100, top: 50, width: 300, height: 200 }, view, 320);
    expect(place).toMatchObject({ mode: 'right', left: 400 + SHEET_GAP, top: 50 });
  });

  test('a glance tile at the foot of the sidebar: the sheet flips up so its whole height is on screen', () => {
    const tile = { left: 8, top: 860, width: 76, height: 36 };
    const place = sheetPlacement(tile, view, 320);
    expect(place.top + 320).toBeLessThanOrEqual(view.height - EDGE);
    expect(place.top).toBe(view.height - EDGE - 320);
  });

  test('a sheet taller than the window starts at the edge (it scrolls inside its own max height)', () => {
    expect(sheetPlacement({ left: 8, top: 860, width: 76, height: 36 }, view, 2000).top).toBe(EDGE);
  });

  test('before the sheet is measured it still keeps the least height on screen', () => {
    expect(sheetPlacement({ left: 8, top: 880, width: 76, height: 20 }, view).top).toBe(view.height - EDGE - MIN_SHEET_HEIGHT);
  });
});
