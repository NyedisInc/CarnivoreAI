/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import {
  FOLDS_KEY, currentFoldKey, isFolded, reloadStatusFolds, sectionFoldKey, statusSubFoldKey, subFoldKey,
} from './task-manager-status-folds.svelte';

afterEach(() => {
  localStorage.clear();
  reloadStatusFolds();
});

describe('retired section names in stored folds', () => {
  test('an explicit choice under an old name holds under the new one, and the old keys are written away once', () => {
    localStorage.setItem(FOLDS_KEY, JSON.stringify({ '12/back_burner': false, '4:waiting_install': true, 'status/4:back_burner': true, '12/done': false }));
    reloadStatusFolds();
    expect(isFolded(sectionFoldKey('12', 'todo'))).toBe(false);
    expect(isFolded(subFoldKey(4, 'waiting'))).toBe(true);
    expect(isFolded(statusSubFoldKey(4, 'todo'))).toBe(true);
    expect(isFolded(sectionFoldKey('12', 'done'))).toBe(false);
    expect(JSON.parse(localStorage.getItem(FOLDS_KEY) ?? '{}')).toEqual({ '12/todo': false, '4:waiting': true, 'status/4:todo': true, '12/done': false });
  });

  test('a choice already stored under the new name wins over the old one', () => {
    localStorage.setItem(FOLDS_KEY, JSON.stringify({ '12/back_burner': false, '12/todo': true }));
    reloadStatusFolds();
    expect(isFolded(sectionFoldKey('12', 'todo'))).toBe(true);
  });

  test('the older array form is read through the new names too', () => {
    localStorage.setItem(FOLDS_KEY, JSON.stringify(['waiting_install']));
    reloadStatusFolds();
    expect(isFolded('waiting')).toBe(true);
  });

  test('a key with no retired section is unchanged', () => {
    expect(currentFoldKey('project/12')).toBe('project/12');
    expect(currentFoldKey('12/review')).toBe('12/review');
  });
});
