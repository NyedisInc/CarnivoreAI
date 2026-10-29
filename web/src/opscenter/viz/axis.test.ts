import { describe, expect, test } from 'vitest';
import { axisCounts, timeLabelCount, valueTickCount, VALUE_TICK_PX } from './axis';

describe('axis label counts follow the plot size', () => {
  test('a short plot gets two value ticks, a tall one more, never past six', () => {
    expect(valueTickCount(0)).toBe(2);
    expect(valueTickCount(70)).toBe(2);
    expect(valueTickCount(3 * VALUE_TICK_PX)).toBe(3);
    expect(valueTickCount(170)).toBe(6);
    expect(valueTickCount(2000)).toBe(6);
  });

  test('every value tick keeps at least its share of the height once the plot fits more than two', () => {
    for (let px = 2 * VALUE_TICK_PX; px <= 400; px += 7) expect(px / valueTickCount(px)).toBeGreaterThanOrEqual(VALUE_TICK_PX);
  });

  test('the quota card case: a 110px card box plots about 70px and carries two ticks, not nine', () => {
    expect(axisCounts({ width: 380, height: 110 }, { top: 12, bottom: 28, left: 43, right: 14 }).value).toBe(2);
  });

  test('time labels thin with width', () => {
    expect(timeLabelCount(150)).toBe(2);
    expect(timeLabelCount(400)).toBe(5);
    expect(timeLabelCount(5000)).toBe(8);
  });
});
