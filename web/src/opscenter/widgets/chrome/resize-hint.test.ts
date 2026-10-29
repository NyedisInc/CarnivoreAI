import { describe, expect, it } from 'vitest';
import { suggestedSizes } from '../fits';
import type { GridSizeName } from '../named-sizes';
import type { FitSize } from '../types';
import {
  guideCandidates,
  guideChevrons,
  guideFloor,
  pickTarget,
  resizeGuide,
  sameSize,
  sizeDistance,
  widthReach,
  type ResizeGuide,
  type WidthReach,
} from './resize-hint';

const CASES: { name: string; sizes: GridSizeName[]; floor: FitSize; reach: WidthReach | null }[] = [
  { name: 'stat tile', sizes: ['small', 'wide'], floor: { w: 1, h: 1 }, reach: null },
  { name: 'list', sizes: ['tall', 'medium', 'large', 'full'], floor: { w: 2, h: 2 }, reach: null },
  { name: 'list beside neighbours in an 11-unit row', sizes: ['tall', 'medium', 'large', 'full'], floor: { w: 2, h: 2 }, reach: { row: 11, narrowest: 1, widest: 9 } },
  { name: 'list alone in an 11-unit row', sizes: ['tall', 'medium', 'large', 'full'], floor: { w: 2, h: 2 }, reach: { row: 11, narrowest: 11, widest: 11 } },
  { name: 'themes', sizes: ['tall', 'medium', 'large'], floor: { w: 2, h: 3 }, reach: null },
  { name: 'terminal', sizes: ['medium', 'large', 'full'], floor: { w: 3, h: 3 }, reach: { row: 13, narrowest: 1, widest: 12 } },
  { name: 'timeline chart (renderer floor 4 x 4)', sizes: ['tall', 'medium', 'large', 'full'], floor: { w: 4, h: 4 }, reach: { row: 10, narrowest: 1, widest: 7 } },
  { name: 'wide only', sizes: ['wide'], floor: { w: 1, h: 1 }, reach: null },
  { name: 'small and full', sizes: ['small', 'full'], floor: { w: 1, h: 1 }, reach: null },
];

function reachable(floor: FitSize, reach: WidthReach | null): FitSize[] {
  const out: FitSize[] = [];
  for (let w = Math.max(floor.w, reach?.narrowest ?? 1); w <= (reach?.widest ?? 14); w += 1) {
    for (let h = floor.h; h <= 9; h += 1) out.push({ w, h });
  }
  return out;
}

function isDeclared(size: FitSize, declared: readonly FitSize[], reach: WidthReach | null): boolean {
  return declared.some((one) => sameSize(one, size) || (!!reach && one.w > reach.row && size.w === reach.row && one.h === size.h));
}

function stepAlong(at: FitSize, guide: ResizeGuide): FitSize {
  if (guide.w) return { w: at.w + (guide.w === 'grow' ? 1 : -1), h: at.h };
  return { w: at.w, h: at.h + (guide.h === 'grow' ? 1 : -1) };
}

describe.each(CASES)('every reachable size of $name', ({ sizes, floor, reach }) => {
  const declared = suggestedSizes({ sizes });
  const candidates = guideCandidates(declared, floor, reach);

  it('aims only at declared sizes the box can reach', () => {
    expect(candidates.length).toBeGreaterThan(0);
    for (const size of candidates) {
      expect(isDeclared(size, declared, reach)).toBe(true);
      expect(size.w >= floor.w && size.h >= floor.h).toBe(true);
      if (reach) expect(size.w >= reach.narrowest && size.w <= reach.widest).toBe(true);
    }
  });

  it('shows chevrons exactly when the size is not a declared one it can reach, and each points toward the target', () => {
    for (const has of reachable(floor, reach)) {
      const target = pickTarget(null, has, candidates);
      const guide = resizeGuide(has, target);
      const onTarget = candidates.some((size) => sameSize(size, has));
      expect(guide === null).toBe(onTarget);
      if (!guide || !target) continue;
      if (guide.w) expect(Math.abs(stepAlong(has, { w: guide.w, h: null }).w - target.w)).toBeLessThan(Math.abs(has.w - target.w));
      if (guide.h) expect(Math.abs(stepAlong(has, { w: null, h: guide.h }).h - target.h)).toBeLessThan(Math.abs(has.h - target.h));
      expect(guide.w === null).toBe(has.w === target.w);
      expect(guide.h === null).toBe(has.h === target.h);
    }
  });

  it('following the chevrons one unit at a time always reaches a declared size, never leaving the reachable sizes', () => {
    for (const start of reachable(floor, reach)) {
      let at = start;
      let held: FitSize | null = null;
      let distance = Infinity;
      for (let step = 0; step < 40; step += 1) {
        held = pickTarget(held, at, candidates);
        const guide = resizeGuide(at, held);
        if (!guide) break;
        expect(isDeclared(held!, declared, reach)).toBe(true);
        expect(sizeDistance(at, held!)).toBeLessThan(distance);
        distance = sizeDistance(at, held!);
        at = stepAlong(at, guide);
        expect(at.w >= floor.w && at.h >= floor.h).toBe(true);
        if (reach) expect(at.w >= reach.narrowest && at.w <= reach.widest).toBe(true);
      }
      expect(candidates.some((size) => sameSize(size, at))).toBe(true);
    }
  });
});

describe('the cases Joe hit live (huddle 62, 2026-10-06)', () => {
  const chartFloor = guideFloor({ w: 2, h: 2 }, 256, { width: 260, height: 120 }, 33);
  const chartCandidates = guideCandidates(suggestedSizes({ sizes: ['tall', 'medium', 'large', 'full'] }), chartFloor, widthReach(1033, 12, [200, 200, 200]));

  it('a 3 x 5 chart below its renderer floor grows its width and drops one row to medium, never toward 2 rows', () => {
    expect(chartFloor).toEqual({ w: 4, h: 4 });
    const target = pickTarget(null, { w: 3, h: 5 }, chartCandidates);
    expect(target).toMatchObject({ w: 4, h: 4 });
    expect(resizeGuide({ w: 3, h: 5 }, target)).toEqual({ w: 'grow', h: 'shrink' });
  });

  it('a chart at its row floor height is never told to shrink below it', () => {
    for (let w = 4; w <= 7; w += 1) {
      const guide = resizeGuide({ w, h: 4 }, pickTarget(null, { w, h: 4 }, chartCandidates));
      expect(guide?.h ?? null).not.toBe('shrink');
    }
  });

  it('a box past the floor but not at a declared size keeps its chevrons (they used to vanish with the plate)', () => {
    const list = guideCandidates(suggestedSizes({ sizes: ['tall', 'medium', 'large', 'full'] }), { w: 2, h: 2 }, null);
    expect(resizeGuide({ w: 3, h: 5 }, pickTarget(null, { w: 3, h: 5 }, list))).not.toBeNull();
  });

  it('never aims at a width the row cannot give a cell beside neighbours', () => {
    const list = guideCandidates(suggestedSizes({ sizes: ['tall', 'medium', 'large', 'full'] }), { w: 2, h: 2 }, widthReach(1033, 12, [200]));
    expect(list.map((size) => size.w)).toEqual([2, 4, 6]);
    expect(pickTarget(null, { w: 8, h: 5 }, list)).toMatchObject({ w: 6, h: 5 });
  });

  it('a lone cell 11 units wide is its full size by width and is only told to fix its height', () => {
    const list = guideCandidates(suggestedSizes({ sizes: ['tall', 'medium', 'large', 'full'] }), { w: 2, h: 2 }, widthReach(1033, 12, []));
    expect(list).toEqual([{ w: 11, h: 5 }]);
    expect(resizeGuide({ w: 11, h: 4 }, pickTarget(null, { w: 11, h: 4 }, list))).toEqual({ w: null, h: 'grow' });
  });

  it('points nowhere when nothing declared can be reached', () => {
    expect(guideCandidates(suggestedSizes({ sizes: ['medium'] }), { w: 2, h: 2 }, { row: 11, narrowest: 11, widest: 11 })).toEqual([]);
    expect(pickTarget(null, { w: 11, h: 4 }, [])).toBeNull();
  });

  it('holds the target between two equally near sizes and lets a much nearer one take over', () => {
    const candidates = suggestedSizes({ sizes: ['tall', 'medium'] });
    const held = pickTarget(null, { w: 3, h: 4 }, candidates);
    expect(held).toMatchObject({ w: 2, h: 4 });
    expect(pickTarget(held, { w: 3, h: 4 }, candidates)).toBe(held);
    expect(pickTarget(held, { w: 4, h: 5 }, candidates)).toMatchObject({ w: 4, h: 4 });
  });
});

describe('guideFloor and widthReach', () => {
  it('reads a body floor so every box rounding to the answer clears it', () => {
    expect(guideFloor({ w: 1, h: 1 }, null, null, 0)).toEqual({ w: 1, h: 1 });
    expect(guideFloor({ w: 1, h: 1 }, null, { width: 140, height: 90 }, 33)).toEqual({ w: 2, h: 3 });
  });
  it('takes the gutters and the neighbours floors out of the row', () => {
    expect(widthReach(1033, 12, [200, 200, 200])).toEqual({ row: 10, narrowest: 1, widest: 4 });
    expect(widthReach(1033, 12, [])).toEqual({ row: 11, narrowest: 11, widest: 11 });
  });
});

describe('resizeGuide', () => {
  it('has one answer per axis', () => {
    expect(resizeGuide({ w: 1, h: 2 }, { w: 2, h: 2 })).toEqual({ w: 'grow', h: null });
    expect(resizeGuide({ w: 1, h: 4 }, { w: 2, h: 2 })).toEqual({ w: 'grow', h: 'shrink' });
    expect(resizeGuide({ w: 8, h: 4 }, { w: 4, h: 2 })).toEqual({ w: 'shrink', h: 'shrink' });
  });
  it('has nothing to say with no target or when already there', () => {
    expect(resizeGuide(null, { w: 2, h: 2 })).toBeNull();
    expect(resizeGuide({ w: 2, h: 2 }, null)).toBeNull();
    expect(resizeGuide({ w: 2, h: 2 }, { w: 2, h: 2 })).toBeNull();
  });
});

describe('guideChevrons', () => {
  it('draws only the edges of an axis that is off', () => {
    expect(guideChevrons({ w: null, h: 'grow' }).map((c) => c.edge)).toEqual(['top', 'bottom']);
    expect(guideChevrons({ w: 'grow', h: null }).map((c) => c.edge)).toEqual(['left', 'right']);
    expect(guideChevrons(null)).toEqual([]);
  });
  it('points each edge the way it moves', () => {
    expect(guideChevrons({ w: 'grow', h: 'grow' })).toEqual([
      { edge: 'top', point: 'up' },
      { edge: 'bottom', point: 'down' },
      { edge: 'left', point: 'left' },
      { edge: 'right', point: 'right' },
    ]);
    expect(guideChevrons({ w: 'shrink', h: 'shrink' })).toEqual([
      { edge: 'top', point: 'down' },
      { edge: 'bottom', point: 'up' },
      { edge: 'left', point: 'right' },
      { edge: 'right', point: 'left' },
    ]);
  });
});
