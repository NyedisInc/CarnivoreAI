import { describe, expect, test } from 'vitest';
import { HYSTERESIS } from '../lib/states';
import { densityRanges, resolveDensity, tierRanges } from './density';
import type { DensityLadders } from './types';

const LADDERS: DensityLadders = {
  width: [
    { name: 'narrow', min: 0 },
    { name: 'medium', min: 300 },
    { name: 'wide', min: 600 },
  ],
  height: [
    { name: 'strip', min: 0 },
    { name: 'full', min: 120 },
  ],
};

describe('resolveDensity', () => {
  test('a step turns on exactly at its minimum and not one pixel before', () => {
    expect(resolveDensity(LADDERS, { width: 299, height: 0 }).width).toBe('narrow');
    expect(resolveDensity(LADDERS, { width: 300, height: 0 }).width).toBe('medium');
    expect(resolveDensity(LADDERS, { width: 599, height: 0 }).width).toBe('medium');
    expect(resolveDensity(LADDERS, { width: 600, height: 0 }).width).toBe('wide');
  });

  test('below the first step answers the first step, never nothing', () => {
    const ladders: DensityLadders = { width: [{ name: 'only', min: 200 }], height: [{ name: 'h', min: 50 }] };
    expect(resolveDensity(ladders, { width: 10, height: 10 })).toEqual({ width: 'only', height: 'h' });
  });

  test('shrinking holds the step until HYSTERESIS pixels below its minimum', () => {
    const held = { width: 'wide', height: 'full' };
    expect(resolveDensity(LADDERS, { width: 600 - HYSTERESIS, height: 120 - HYSTERESIS }, held)).toEqual(held);
    expect(resolveDensity(LADDERS, { width: 600 - HYSTERESIS - 1, height: 120 - HYSTERESIS - 1 }, held)).toEqual({
      width: 'medium',
      height: 'strip',
    });
  });

  test('growing is not delayed by hysteresis', () => {
    expect(resolveDensity(LADDERS, { width: 300, height: 0 }, { width: 'narrow', height: 'strip' }).width).toBe('medium');
  });

  test('the two axes are resolved independently', () => {
    expect(resolveDensity(LADDERS, { width: 700, height: 10 })).toEqual({ width: 'wide', height: 'strip' });
    expect(resolveDensity(LADDERS, { width: 10, height: 700 })).toEqual({ width: 'narrow', height: 'full' });
  });
});

describe('tierRanges', () => {
  test('each step ends one pixel below the next and the last runs to the ceiling', () => {
    expect(tierRanges(LADDERS.width)).toEqual([
      { name: 'narrow', min: 0, max: 299 },
      { name: 'medium', min: 300, max: 599 },
      { name: 'wide', min: 600, max: null },
    ]);
    expect(tierRanges(LADDERS.width, 1200).at(-1)).toEqual({ name: 'wide', min: 600, max: 1200 });
  });

  test('densityRanges reads each axis ceiling from the bounds', () => {
    const ranges = densityRanges(LADDERS, { minW: 0, minH: 0, maxH: 400 });
    expect(ranges.width.at(-1)?.max).toBeNull();
    expect(ranges.height.at(-1)?.max).toBe(400);
  });
});
