import { describe, expect, test } from 'vitest';
import { MK2_CHIPS_FULL_FROM_PX, MK2_CHIPS_ICON_BELOW_PX, MK2_CHIP_ICON, MK2_CHIP_ORDER, chipMode } from './mk2-chips';

describe('chipMode', () => {
  test('the three looks at their widths, the edges included', () => {
    expect(chipMode(MK2_CHIPS_FULL_FROM_PX)).toBe('full');
    expect(chipMode(MK2_CHIPS_FULL_FROM_PX - 1)).toBe('count');
    expect(chipMode(MK2_CHIPS_ICON_BELOW_PX)).toBe('count');
    expect(chipMode(MK2_CHIPS_ICON_BELOW_PX - 1)).toBe('icon');
  });

  test('the row never wraps for a count: a width that shows words or counts is wide enough for the widest counts', () => {
    expect(chipMode(320)).toBe('count');
    expect(chipMode(340)).toBe('count');
    expect(MK2_CHIPS_FULL_FROM_PX).toBe(363);
    expect(MK2_CHIPS_ICON_BELOW_PX).toBe(249);
  });

  test('an unmeasured width is the full look, never a smaller guess', () => {
    expect(chipMode(0)).toBe('full');
    expect(chipMode(Number.NaN)).toBe('full');
  });

  test('every chip has an icon', () => {
    expect(MK2_CHIP_ORDER.every((id) => !!MK2_CHIP_ICON[id])).toBe(true);
  });
});
