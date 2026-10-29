import { describe, expect, test } from 'vitest';
import { agoWords, nextWords, runTimeWords } from './run-chart';
import { setLocale } from '../../lib/i18n/index.svelte';

setLocale('en');

describe('the run chart words', () => {
  test('a run time reads in ms below a second, seconds below a minute, then minutes', () => {
    expect(runTimeWords(4.2)).toBe('4 ms');
    expect(runTimeWords(1400)).toBe('1.4s');
    expect(runTimeWords(125_000)).toBe('2m 05s');
    expect(runTimeWords(null)).toBe('');
  });

  test('an age reads in seconds below a minute, then the coarse ago words', () => {
    expect(agoWords(12)).toBe('12s ago');
    expect(agoWords(180)).toBe('3m ago');
    expect(agoWords(7200)).toBe('2h ago');
    expect(agoWords(null)).toBe('');
  });

  test('the next run reads "in" a time, never negative', () => {
    expect(nextWords(300)).toBe('in 5m 00s');
    expect(nextWords(-5)).toBe('in 0m 00s');
    expect(nextWords(null)).toBe('');
    expect(nextWords(86_399)).toBe('in 23h 59m');
    expect(nextWords(6 * 86_400 + 23 * 3_600 + 59)).toBe('in 6d 23h');
  });
});
