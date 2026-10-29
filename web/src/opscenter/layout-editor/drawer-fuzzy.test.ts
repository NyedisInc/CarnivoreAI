import { describe, expect, test } from 'vitest';
import { fuzzyMatch, highlightParts } from './drawer-fuzzy';

describe('fuzzyMatch', () => {
  test('letters in order match, case ignored, and the indices are the matched letters', () => {
    expect(fuzzyMatch('NTS', 'notes')?.indices).toEqual([0, 2, 4]);
    expect(fuzzyMatch('mach', 'Machine stats')?.indices).toEqual([0, 1, 2, 3]);
  });

  test('letters out of order, absent or too many do not match; a blank query matches nothing', () => {
    expect(fuzzyMatch('zz', 'notes')).toBeNull();
    expect(fuzzyMatch('sn', 'notes')).toBeNull();
    expect(fuzzyMatch('notess', 'notes')).toBeNull();
    expect(fuzzyMatch('', 'notes')).toBeNull();
    expect(fuzzyMatch('   ', 'notes')).toBeNull();
  });

  test('a contiguous match outranks a scattered one', () => {
    const tight = fuzzyMatch('abc', 'abcdef')!;
    const loose = fuzzyMatch('abc', 'axbxcx')!;
    expect(tight.score).toBeGreaterThan(loose.score);
  });

  test('a word start outranks a letter in the middle of a word', () => {
    const start = fuzzyMatch('t', 'closed tasks')!;
    const middle = fuzzyMatch('t', 'closed notes')!;
    expect(start.score).toBeGreaterThan(middle.score);
  });

  test('the best alignment wins, not the first greedy one', () => {
    expect(fuzzyMatch('ab', 'xaxb ab')?.indices).toEqual([5, 6]);
  });

  test('a shorter text beats a longer one with the same match', () => {
    expect(fuzzyMatch('note', 'notes')!.score).toBeGreaterThan(fuzzyMatch('note', 'notes and more')!.score);
  });
});

describe('highlightParts', () => {
  test('splits into matched and unmatched runs covering the whole text', () => {
    expect(highlightParts('notes', [0, 1, 4])).toEqual([
      { text: 'no', hit: true },
      { text: 'te', hit: false },
      { text: 's', hit: true },
    ]);
  });

  test('no indices is one plain run, and an empty text is no runs', () => {
    expect(highlightParts('notes', [])).toEqual([{ text: 'notes', hit: false }]);
    expect(highlightParts('', [])).toEqual([]);
  });
});
