import { describe, expect, test } from 'vitest';
import { FUZZY_MIN_LETTERS, FUZZY_SPAN, fuzzyMatch, wordMatches } from './task-manager-fuzzy';

describe('wordMatches', () => {
  test('a substring matches, case aside', () => {
    expect(wordMatches('board', 'review board')).toBe(true);
    expect(wordMatches('boards', 'review board')).toBe(false);
  });

  test('letters in order inside a short window match; the same letters spread wide do not', () => {
    expect(wordMatches('rvwbrd', 'review board')).toBe(true);
    const wide = `r${' '.repeat(40)}v${' '.repeat(40)}w`;
    expect(wordMatches('rvw', wide)).toBe(false);
    expect(wordMatches('rvw', 'review')).toBe(true);
  });

  test('a word shorter than the minimum must be a substring', () => {
    expect(FUZZY_MIN_LETTERS).toBe(3);
    expect(wordMatches('rd', 'review board')).toBe(true);
    expect(wordMatches('rb', 'review board')).toBe(false);
  });

  test('the window is a fixed multiple of the word length', () => {
    expect(FUZZY_SPAN).toBe(2);
    expect(wordMatches('abc', 'a b c')).toBe(true);
    expect(wordMatches('abc', 'a    b    c')).toBe(false);
  });
});

describe('fuzzyMatch', () => {
  test('an empty or blank query matches everything', () => {
    expect(fuzzyMatch('', 'anything')).toBe(true);
    expect(fuzzyMatch('   ', 'anything')).toBe(true);
  });

  test('every word of the query must match', () => {
    expect(fuzzyMatch('mrkr filtr', 'Marker filter set')).toBe(true);
    expect(fuzzyMatch('marker zzz', 'Marker filter set')).toBe(false);
  });

  test('case is ignored on both sides', () => {
    expect(fuzzyMatch('MARKER', 'a marker row')).toBe(true);
    expect(fuzzyMatch('marker', 'A MARKER ROW')).toBe(true);
  });
});
