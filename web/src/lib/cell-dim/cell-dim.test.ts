/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { applyStoredCellDim, setCellDim, storedCellDim } from './cell-dim';

const root = () => document.documentElement.style.getPropertyValue('--oc-cell-dim');

afterEach(() => {
  localStorage.clear();
  document.documentElement.style.removeProperty('--oc-cell-dim');
  vi.restoreAllMocks();
});

describe('cell dim', () => {
  test('setting a percent paints the opacity and remembers it', () => {
    setCellDim(35);
    expect(Number(root())).toBeCloseTo(0.65);
    expect(storedCellDim()).toBe(35);
    document.documentElement.style.removeProperty('--oc-cell-dim');
    applyStoredCellDim();
    expect(Number(root())).toBeCloseTo(0.65);
  });

  test('nothing stored leaves the token alone, and blocked storage does not throw', () => {
    applyStoredCellDim();
    expect(root()).toBe('');
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => applyStoredCellDim()).not.toThrow();
    expect(storedCellDim()).toBe(20);
  });
});
