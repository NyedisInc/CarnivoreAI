/** @vitest-environment jsdom */
import { beforeEach, describe, expect, test } from 'vitest';
import { BAR_GRAB_MIN_PX, CELL_WIDTH_FALLBACK_PX, TERMINAL_MIN_COLUMNS } from '../session-rail/bar-limits';
import { MIN_WIDTH_PX, STORAGE_KEY, clamp, maxWidth, readWidth } from './resize';

beforeEach(() => {
  (window as { innerWidth: number }).innerWidth = 1600;
  localStorage.clear();
});

describe('drawer width limits', () => {
  test('the minimum is the grab minimum and the maximum leaves the terminal 60 columns', () => {
    expect(MIN_WIDTH_PX).toBe(BAR_GRAB_MIN_PX);
    expect(maxWidth()).toBe(Math.floor(1600 - TERMINAL_MIN_COLUMNS * CELL_WIDTH_FALLBACK_PX));
    expect(clamp(1)).toBe(BAR_GRAB_MIN_PX);
    expect(clamp(700)).toBe(700);
  });

  test('a stored width beyond the limits is clamped on read', () => {
    localStorage.setItem(STORAGE_KEY, '99999');
    expect(readWidth()).toBe(maxWidth());
  });
});
