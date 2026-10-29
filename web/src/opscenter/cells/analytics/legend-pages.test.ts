import { describe, expect, test } from 'vitest';
import { legendFitsOneRow, legendPages } from './legend-pages';

describe('legendPages: whole items per page', () => {
  test('a page takes items while they fit whole and the rest go to the next page', () => expect(legendPages([40, 40, 40], 100, 8)).toEqual([0, 2]));

  test('no page holds more than its room (no partial item)', () => {
    const widths = [60, 70, 50, 90, 30];
    const room = 130;
    const starts = legendPages(widths, room, 8);
    starts.forEach((start, page) => {
      const end = starts[page + 1] ?? widths.length;
      const used = widths.slice(start, end).reduce((sum, width, at) => sum + width + (at === 0 ? 0 : 8), 0);
      expect(used).toBeLessThanOrEqual(room);
    });
  });

  test('an item wider than the room stands alone on its own page', () => expect(legendPages([150, 30, 30], 100, 8)).toEqual([0, 1]));

  test('every item lands on exactly one page, in order', () => {
    const starts = legendPages([50, 50, 50, 50], 110, 8);
    expect(starts[0]).toBe(0);
    expect([...starts].sort((a, b) => a - b)).toEqual(starts);
  });

  test('no items, no pages', () => expect(legendPages([], 100, 8)).toEqual([]));
});

describe('legendFitsOneRow', () => {
  test('a row that fits needs no pager', () => expect(legendFitsOneRow([40, 40], 100, 8)).toBe(true));
  test('a row that does not fit pages', () => expect(legendFitsOneRow([60, 60], 100, 8)).toBe(false));
  test('no items fit trivially', () => expect(legendFitsOneRow([], 0, 8)).toBe(true));
});
