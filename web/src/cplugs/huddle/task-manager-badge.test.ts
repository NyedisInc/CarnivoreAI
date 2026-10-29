import { describe, expect, test } from 'vitest';
import { AGGREGATE, needsYouTotal } from './huddle-model';
import { BADGE_DEFAULT, badgeFrom } from './task-manager-prefs.svelte';

const rows: { key: string; attention?: number; status_counts?: Record<string, number> }[] = [
  { key: '12', attention: 2, status_counts: { question: 1, review: 1, open: 4, working: 2, scheduled: 1 } },
  { key: '18', attention: 1, status_counts: { review: 1, waiting: 3 } },
];

describe('needsYouTotal with ticked statuses', () => {
  test('sums only the ticked statuses across every list, or one list', () => {
    expect(needsYouTotal(rows, AGGREGATE, ['question', 'review'])).toBe(3);
    expect(needsYouTotal(rows, AGGREGATE, ['open', 'working'])).toBe(6);
    expect(needsYouTotal(rows, '18', ['waiting', 'scheduled'])).toBe(3);
    expect(needsYouTotal(rows, '12', ['waiting'])).toBeNull();
  });
  test('no ticks counts nothing; no statuses argument keeps the questions-plus-reviews number', () => {
    expect(needsYouTotal(rows, AGGREGATE, [])).toBeNull();
    expect(needsYouTotal(rows, AGGREGATE)).toBe(3);
  });
  test('an older server row without status_counts answers its attention', () => {
    expect(needsYouTotal([{ key: '12', attention: 5 }], '12', ['open'])).toBe(5);
  });
});

describe('badgeFrom', () => {
  test('unset settings read as the default (questions and reviews)', () => {
    expect(badgeFrom(undefined)).toEqual(BADGE_DEFAULT);
    expect(badgeFrom({})).toEqual({ question: true, review: true, open: false, working: false, waiting: false, scheduled: false });
  });
  test('stored booleans win, anything else is ignored', () => {
    expect(badgeFrom({ badgeQuestions: false, badgeOpen: true, badgeWorking: 'yes' })).toMatchObject({ question: false, review: true, open: true, working: false });
  });
});
