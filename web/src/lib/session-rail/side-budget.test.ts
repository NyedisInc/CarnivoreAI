/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test } from 'vitest';
import { CELL_WIDTH_FALLBACK_PX, TERMINAL_MIN_COLUMNS } from './bar-limits';
import { railOutSizes } from './rail-out-size.svelte';
import { sideBudget } from './side-budget.svelte';
import { apply, maxWidth, refit } from '../drawer/resize';

const FLOOR = Math.ceil(TERMINAL_MIN_COLUMNS * CELL_WIDTH_FALLBACK_PX);
const setWindow = (w: number) => {
  (window as { innerWidth: number }).innerWidth = w;
};

beforeEach(() => {
  localStorage.clear();
  sideBudget.reset();
  setWindow(1600);
});

describe('side budget', () => {
  test('the drawer is capped by the slide-out width', () => {
    sideBudget.hold('slideout', 500);
    expect(maxWidth()).toBeLessThanOrEqual(1600 - 500 - FLOOR + 1);
    const taken = apply(5000);
    expect(taken + 500 + FLOOR).toBeLessThanOrEqual(1600 + 1);
  });

  test('the slide-out is capped by the drawer width', () => {
    sideBudget.hold('drawer', 600);
    expect(railOutSizes.max('side', 1600) + 600 + FLOOR).toBeLessThanOrEqual(1600 + 1);
    const taken = railOutSizes.set('side', 5000, 1600);
    expect(taken + 600 + FLOOR).toBeLessThanOrEqual(1600 + 1);
  });

  test('the bottom rail is not narrowed by the drawer', () => {
    sideBudget.hold('drawer', 600);
    expect(railOutSizes.available('bottom', 800)).toBe(800);
  });

  test('a shrinking window clamps the drawer on the fly and a growing one gives it back', () => {
    apply(900);
    setWindow(1000);
    refit();
    expect(sideBudget.otherThan('slideout')).toBeLessThanOrEqual(1000 - FLOOR + 1);
    setWindow(1600);
    refit();
    expect(sideBudget.otherThan('slideout')).toBe(900);
  });
});
