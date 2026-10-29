import { describe, expect, test } from 'vitest';
import { ALL_FILTERS_ON, filterCounts, phoneRows, timeMs, visibleGaps, visibleMarks } from './model';
import { timelineFixture } from './fixture';
import type { Filters } from './types';

const off = (...keys: (keyof Filters)[]): Filters => ({ ...ALL_FILTERS_ON, ...Object.fromEntries(keys.map((k) => [k, false])) } as Filters);

describe('marks, gaps and the filters', () => {
  test('each filter hides only its own kind', () => {
    const data = timelineFixture();
    const kinds = (f: Filters) => visibleMarks(data, f).map((m) => m.kind).sort();
    expect(kinds(off('bookmarks'))).not.toContain('bookmark');
    expect(kinds(off('compacts'))).not.toContain('compact');
    expect(kinds(off('restarts'))).not.toContain('restart');
    expect(kinds(off('restores'))).not.toContain('restore');
    expect(kinds(off('bookmarks', 'compacts', 'restarts', 'restores'))).toEqual([]);
    expect(visibleGaps(data, off('sleeps'))).toEqual([]);
    expect(visibleGaps(data, ALL_FILTERS_ON)).toHaveLength(2);
  });

  test('the counts say how much is behind each toggle', () => {
    expect(filterCounts(timelineFixture())).toEqual({ bookmarks: 1, compacts: 1, restarts: 2, sleeps: 2, restores: 1 });
  });

  test('timeMs reads ISO text and nothing else', () => {
    expect(timeMs('2026-10-10T10:00:00Z')).toBe(Date.UTC(2026, 9, 10, 10));
    expect(timeMs('nope')).toBeNull();
    expect(timeMs(null)).toBeNull();
  });
});

describe('the phone list', () => {
  test('bar starts, marks and sleeps come in time order, oldest first', () => {
    const rows = phoneRows(timelineFixture(), ALL_FILTERS_ON);
    expect(rows.map((r) => r.key)).toEqual([
      'bar:conv-a', 'restart:conv-a:1', 'sleep:conv-a:1', 'bar:conv-b', 'compact:conv-b:9', 'restore:conv-b:20261010T112500Z-kill',
      'bar:conv-c', 'bookmark:1', 'restart:conv-c:2', 'sleep:conv-c:2',
    ]);
  });

  test('the filters apply to the list too, and a bar start always stays', () => {
    const rows = phoneRows(timelineFixture(), off('restarts', 'sleeps', 'restores'));
    expect(rows.map((r) => r.type)).toEqual(['began', 'began', 'mark', 'began', 'mark']);
  });
});
