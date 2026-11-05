import { describe, expect, test } from 'vitest';
import { inSplitZone, keysEndOf, splitOffer } from './rail-aim';

const AREA = { start: 0, end: 400 };

describe('the split zone', () => {
  test('past the middle AND past the last key, inside the area', () => {
    expect(inSplitZone(AREA, 120, 300)).toBe(true);
    expect(inSplitZone(AREA, 120, 150)).toBe(false);
    expect(inSplitZone(AREA, 320, 300)).toBe(false);
    expect(inSplitZone(AREA, 320, 330)).toBe(true);
    expect(inSplitZone(AREA, null, 200)).toBe(true);
    expect(inSplitZone(AREA, null, 199)).toBe(false);
    expect(inSplitZone(AREA, 120, 401)).toBe(false);
  });

  test('the far end of a bar that starts mid-screen is measured from the area, not from zero', () => {
    expect(inSplitZone({ start: 700, end: 900 }, 740, 820)).toBe(true);
    expect(inSplitZone({ start: 700, end: 900 }, 740, 790)).toBe(false);
  });
});

describe('the offer', () => {
  test('keys that fit in the first half: the split is offered anywhere over the area, and dropped on in the far half', () => {
    expect(splitOffer(AREA, 100, 50)).toBe('offer');
    expect(splitOffer(AREA, 100, 150)).toBe('offer');
    expect(splitOffer(AREA, 100, 300)).toBe('drop');
    expect(splitOffer(AREA, null, 10)).toBe('offer');
  });

  test('keys that reach past the middle: nothing over the keys, the drop only past them', () => {
    expect(splitOffer(AREA, 300, 50)).toBeNull();
    expect(splitOffer(AREA, 300, 250)).toBeNull();
    expect(splitOffer(AREA, 300, 350)).toBe('drop');
  });

  test('the far edge of the last key', () => {
    expect(keysEndOf([40, 72, 104])).toBe(104);
    expect(keysEndOf([])).toBeNull();
  });
});
