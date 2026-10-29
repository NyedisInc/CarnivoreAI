import { describe, expect, test } from 'vitest';
import { LEGEND_MIN_TEXT_PX, LEGEND_PAGER_PX, legendTextWidth } from './legend-fit';

describe('legendTextWidth', () => {
  test('caps an item so swatch, gap, text and the pager fit one legend row', () => {
    const canvas = 236;
    const text = legendTextWidth(canvas, 0, 14, 10);
    expect(text + 10 + 5 + LEGEND_PAGER_PX + 14).toBeLessThanOrEqual(canvas);
  });

  test('a wider canvas allows a longer name', () => expect(legendTextWidth(640, 84, 14, 25)).toBeGreaterThan(legendTextWidth(236, 0, 14, 10)));

  test('a tiny canvas still keeps a few letters', () => expect(legendTextWidth(60, 0, 14, 10)).toBe(LEGEND_MIN_TEXT_PX));
});
