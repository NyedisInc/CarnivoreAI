import { describe, expect, test } from 'vitest';
import { feedTookWords, tookWords } from './words';

const run = (s: number) => ({ started_at: 1000, ended_at: 1000 + s });

describe('feedTookWords', () => {
  test.each([
    [59, '59 s'],
    [60, '1 min'],
    [300, '5 min'],
    [3599, '59 min'],
    [3600, '1 h'],
    [5400, '1.5 h'],
    [36000, '10 h'],
    [43200, '12 h'],
  ])('%i s -> %s', (s, text) => {
    expect(feedTookWords(run(s))).toBe(text);
  });

  test('an unfinished run has no text, the pane and reader keep the full form', () => {
    expect(feedTookWords({ started_at: 1, ended_at: null })).toBeNull();
    expect(tookWords(run(300))).toBe('5 min 0 s');
  });

  test('the longest feed-face text fits the 46 px took column', () => {
    const longest = [59, 3599, 35999, 359999].map((s) => feedTookWords(run(s)) as string).sort((a, b) => b.length - a.length)[0]!;
    expect(longest.length * 11 * 0.6).toBeLessThanOrEqual(46);
  });
});
