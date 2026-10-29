/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync } from 'svelte';

import { createSortPref } from './list-sort.svelte';

afterEach(() => {
  localStorage.clear();
});

describe('createSortPref', () => {
  test('starts on the fallback when nothing is stored', () => {
    const pref = createSortPref('carnivore.test.sortA', ['a', 'b'] as const, 'a');
    expect(pref.value).toBe('a');
  });

  test('an unrecognised stored value degrades to the fallback, not a crash', () => {
    localStorage.setItem('carnivore.test.sortB', 'not-a-real-key');
    const pref = createSortPref('carnivore.test.sortB', ['a', 'b'] as const, 'b');
    expect(pref.value).toBe('b');
  });

  test('set() updates the reactive value immediately', () => {
    const pref = createSortPref('carnivore.test.sortC', ['a', 'b'] as const, 'a');
    pref.set('b');
    flushSync();
    expect(pref.value).toBe('b');
  });

  test('set() persists to localStorage, read back by a fresh instance', () => {
    const first = createSortPref('carnivore.test.sortD', ['a', 'b'] as const, 'a');
    first.set('b');
    const second = createSortPref('carnivore.test.sortD', ['a', 'b'] as const, 'a');
    expect(second.value).toBe('b');
  });

  test('two cards keyed differently do not see each other\'s choice', () => {
    const projects = createSortPref('carnivore.test.sortE.projects', ['name', 'last_used'] as const, 'last_used');
    const closed = createSortPref('carnivore.test.sortE.closed', ['name', 'recent'] as const, 'recent');
    projects.set('name');
    expect(projects.value).toBe('name');
    expect(closed.value).toBe('recent');
  });
});
