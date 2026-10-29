import { describe, expect, test } from 'vitest';
import { hasOpenSteps, parseSteps, summarize, type StepsEntry } from './task-manager-steps';

function entry(done: number, doing: number, todo: number): StepsEntry {
  const statuses = [...Array(done).fill('completed'), ...Array(doing).fill('in_progress'), ...Array(todo).fill('pending')];
  return {
    tasks: statuses.map((status, n) => ({ id: String(n), subject: `step ${n}`, active_form: status === 'in_progress' ? 'running tests' : null, status })),
    counts: { pending: todo, in_progress: doing, completed: done },
  };
}

describe('huddle steps', () => {
  test('summarize reads "3 of 7, now: running tests"', () => {
    expect(summarize(entry(3, 1, 3))).toEqual({ done: 3, total: 7, now: 'running tests' });
  });

  test('now is null with nothing running, and falls back to the subject without a present-tense line', () => {
    expect(summarize(entry(1, 0, 2)).now).toBeNull();
    const bare = entry(0, 1, 0);
    bare.tasks[0]!.active_form = null;
    expect(summarize(bare).now).toBe('step 0');
  });

  test('an all-complete or missing list has no open steps', () => {
    expect(hasOpenSteps(entry(3, 0, 0))).toBe(false);
    expect(hasOpenSteps(null)).toBe(false);
    expect(hasOpenSteps(entry(0, 0, 1))).toBe(true);
  });

  test('parseSteps keeps open entries per list, drops finished and malformed ones', () => {
    const body = { lists: {
      '12': { items: { '7': entry(1, 1, 1), '8': entry(2, 0, 0) } },
      '13': { items: { '9': entry(1, 0, 0) } },
      '14': null,
    } };
    const out = parseSteps(body);
    expect(Object.keys(out)).toEqual(['12']);
    expect(Object.keys(out['12']!.items)).toEqual(['7']);
    expect(Object.keys(out['12']!)).toEqual(['items']);
    expect(parseSteps(null)).toEqual({});
    expect(parseSteps({ lists: 'x' })).toEqual({});
  });
});
