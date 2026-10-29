import { describe, expect, test } from 'vitest';
import { RANK_BARE_ROW_PX, RANK_PAD_PX, rankedRowPlan, wholeRowCount } from './rank-rows';

describe('rankedRowPlan', () => {
  test('an unmeasured room shows every row with bars', () => expect(rankedRowPlan(0, 8, 4)).toEqual({ count: 4, bars: true }));
  test('a roomy list keeps bars and as many rows as fit', () => expect(rankedRowPlan(110, 8, 4)).toEqual({ count: 3, bars: true }));
  test('a short room drops the bars and keeps the rows that fit', () => expect(rankedRowPlan(54, 8, 4)).toEqual({ count: 2, bars: false }));
  test('a room too short for one whole row draws none, never a half row', () => expect(rankedRowPlan(10, 8, 4)).toEqual({ count: 0, bars: false }));
  test('a room that holds one bare row shows exactly it', () => expect(rankedRowPlan(RANK_PAD_PX + RANK_BARE_ROW_PX, 8, 4)).toEqual({ count: 1, bars: false }));
  test('never more rows than the answer holds', () => expect(rankedRowPlan(0, 2, 4).count).toBe(2));
});

describe('wholeRowCount', () => {
  test('counts the leading rows that end inside the room', () => expect(wholeRowCount(100, [30, 60, 90, 120])).toBe(3));
  test('a half cut first row counts as none', () => expect(wholeRowCount(20, [30, 60])).toBe(0));
  test('a row exactly filling the room is whole', () => expect(wholeRowCount(60, [30, 60, 90])).toBe(2));
  test('a row cut by the edge ends the count even if a later one would fit', () => expect(wholeRowCount(70, [30, 80, 60])).toBe(1));
  test('every row whole counts them all', () => expect(wholeRowCount(500, [30, 60])).toBe(2));
});
