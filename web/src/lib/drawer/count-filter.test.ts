/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { activeCountFilter, setCountFilter, toggleCountFilter } from './count-filter.svelte';
import { effectiveQuery, FILTER_ONLY_QUERY, matchesRow, noMatchesHtml, setQuery } from './search';

const rows = [
  { name: 'alpha', status: 'working' },
  { name: 'beta', status: 'idle', unread: true },
  { name: 'gamma', status: 'idle' },
];

afterEach(() => {
  setCountFilter(null);
  setQuery('');
});

test('no filter and no text means no query at all', () => {
  expect(effectiveQuery()).toBe('');
});

test('a filter alone is a non-empty query that keeps only the rows its count adds up', () => {
  setCountFilter('working');
  expect(effectiveQuery()).toBe(FILTER_ONLY_QUERY);
  expect(rows.filter((r) => matchesRow(r, effectiveQuery())).map((r) => r.name)).toEqual(['alpha']);
});

test('the filter and the search text both apply', () => {
  setCountFilter('active');
  setQuery('ta');
  expect(effectiveQuery()).toBe('ta');
  expect(rows.filter((r) => matchesRow(r, effectiveQuery())).map((r) => r.name)).toEqual(['beta']);
});

test('a second click on the same count clears it, another count replaces it', () => {
  toggleCountFilter('unread');
  expect(activeCountFilter()).toBe('unread');
  toggleCountFilter('working');
  expect(activeCountFilter()).toBe('working');
  toggleCountFilter('working');
  expect(activeCountFilter()).toBeNull();
  expect(rows.every((r) => matchesRow(r, ''))).toBe(true);
});

test('an empty filtered list says so in the filter words, not with the sentinel', () => {
  const html = noMatchesHtml(FILTER_ONLY_QUERY);
  expect(html).toContain('no agents match this count');
  expect(html).not.toContain('\u0001');
});
