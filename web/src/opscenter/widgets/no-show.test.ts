import { describe, expect, test } from 'vitest';
import { NO_SHOW_THRESHOLDS, isNoShow, sizeClassOf } from './no-show';

const floor = (w: number, h: number) => ({ min: { w, h } });

describe('no-show thresholds', () => {
  test('the size class follows the larger side of the floor', () => {
    expect(sizeClassOf(floor(2, 1))).toBe('small');
    expect(sizeClassOf(floor(3, 2))).toBe('medium');
    expect(sizeClassOf(floor(5, 4))).toBe('large');
  });

  test('a box under its class threshold on either axis is no-show, at or over it is not', () => {
    for (const [name, fits] of [['small', floor(1, 1)], ['medium', floor(4, 2)], ['large', floor(6, 3)]] as const) {
      const t = NO_SHOW_THRESHOLDS[name];
      expect(isNoShow(fits, { width: t.width - 1, height: 999 })).toBe(true);
      expect(isNoShow(fits, { width: 999, height: t.height - 1 })).toBe(true);
      expect(isNoShow(fits, { width: t.width, height: t.height })).toBe(false);
    }
  });

  test('a bigger class needs more room than a smaller one', () => {
    const box = { width: 200, height: 110 };
    expect(isNoShow(floor(1, 1), box)).toBe(false);
    expect(isNoShow(floor(6, 3), box)).toBe(true);
  });

  test('an unmeasured box is never no-show', () => {
    expect(isNoShow(floor(6, 3), null)).toBe(false);
    expect(isNoShow(floor(6, 3), { width: 0, height: 0 })).toBe(false);
  });
});
